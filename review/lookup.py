from ledger_core import InvalidInput, MissingRecord, name
from review.cold import parse_item
from review.storage import load_frozen_signoff


def read_signoff(connection, signoff_id):
    name(signoff_id, 'signoff id')
    signoff = load_frozen_signoff(connection, signoff_id)
    if signoff is None:
        raise MissingRecord(f'unknown signoff {signoff_id!r}')
    return signoff


def read_archive(medium, archive_id):
    """Read one archived signoff back from the cold medium alone.

    Only an intact sealed item whose verified archive identity matches can be
    checked out. Slots that are empty, still writing or burned never qualify.
    """
    name(archive_id, 'archive id')
    sealed_items = []
    damaged = False
    for slot in range(medium.slot_count):
        if medium.status(slot) != 'sealed':
            continue
        kind, claimed, signoff = parse_item(medium.read_slot(slot))
        if kind == 'ok':
            if claimed == archive_id:
                sealed_items.append(signoff)
        elif kind == 'damaged' and (claimed is None or claimed == archive_id):
            damaged = True
    if len(sealed_items) > 1:
        raise InvalidInput(f'archive {archive_id!r} has conflicting sealed items')
    if sealed_items:
        return sealed_items[0]
    if damaged:
        raise InvalidInput(f'archive {archive_id!r} has a damaged sealed item')
    raise MissingRecord(f'no sealed archive item for {archive_id!r}')
