from archive_medium import ReplyLost
from ledger_core import MissingRecord, NameConflict, name
from mirror.frontiers import require_frontier
from mirror.materialization import read_received_ledger
from mirror.storage import mirror_transaction
from review.cold import encode_item
from review.storage import (
    ColdArchive,
    FrozenSignoff,
    command_cold_archive_slot,
    load_cold_archive,
    load_current_reviews,
    load_frozen_signoff,
    seal_cold_archive,
    store_cold_archive,
    store_signoff,
)


def create_signoff(connection, signoff_id, day, issue):
    name(signoff_id, 'signoff id')
    with mirror_transaction(connection):
        require_frontier(connection, day, issue)
        existing = load_frozen_signoff(connection, signoff_id)
        if existing is not None:
            if (existing.ledger.day, existing.ledger.issue) != (day, issue):
                raise NameConflict(f'signoff {signoff_id!r} is bound to another request')
            return existing
        ledger = read_received_ledger(connection, day, issue)
        reviews = load_current_reviews(connection, day, issue)
        signoff = FrozenSignoff(signoff_id, ledger,
                               tuple(reviews.get(row.key.row_id) for row in ledger.rows))
        store_signoff(connection, signoff)
        return signoff


def _empty_slot(medium):
    for slot in range(medium.slot_count):
        if medium.status(slot) == 'empty':
            return slot
    return None


def archive(connection, archive_id, signoff_id, medium):
    """Archive one frozen signoff onto a write-once cold medium.

    The night ledger first commits the binding and the commanded slot, then the
    medium settles the write on its own commit boundary. Returns
    ``('pending', None)``, ``('full', None)`` or ``('sealed', receipt)`` with
    ``receipt == (archive_id, signoff_id, medium_id, slot)``.
    """
    name(archive_id, 'archive id')
    name(signoff_id, 'signoff id')
    medium_id = name(medium.medium_id, 'medium id')
    with mirror_transaction(connection):
        record = load_cold_archive(connection, archive_id)
        if record is not None and (record.signoff_id, record.medium_id) != (signoff_id, medium_id):
            raise NameConflict(f'archive {archive_id!r} is bound to another signoff or medium')
        signoff = load_frozen_signoff(connection, signoff_id)
        if signoff is None:
            raise MissingRecord(f'unknown signoff {signoff_id!r}')
        if record is None:
            record = ColdArchive(archive_id, signoff_id, medium_id, None, False)
            store_cold_archive(connection, record)
        if record.sealed:
            return 'sealed', (archive_id, signoff_id, medium_id, record.slot)
        target = record.slot
        if target is not None:
            state = medium.status(target)
            if state == 'writing':
                # The accepted command may still seal; wait and keep free slots untouched.
                return 'pending', None
            if state == 'sealed':
                seal_cold_archive(connection, archive_id, target)
                return 'sealed', (archive_id, signoff_id, medium_id, target)
            if state == 'burned':
                # The accepted command is settled as burned, so another empty slot may be used.
                target = None
            # 'empty' means the command never landed; retry the same slot below.
        if target is None:
            target = _empty_slot(medium)
            if target is None:
                return 'full', None
            command_cold_archive_slot(connection, archive_id, target)
        body = encode_item(archive_id, signoff)
    try:
        medium.write(target, body)
    except ReplyLost:
        # The device accepted the command but the reply was lost; the slot stays
        # recorded as commanded so a later call can settle it from the medium.
        return 'pending', None
    with mirror_transaction(connection):
        seal_cold_archive(connection, archive_id, target)
    return 'sealed', (archive_id, signoff_id, medium_id, target)
