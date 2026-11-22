from ledger_core import NameConflict, name
from mirror.frontiers import require_frontier
from mirror.materialization import read_received_ledger
from mirror.storage import mirror_transaction
from review.storage import FrozenSignoff, load_current_reviews, load_frozen_signoff, store_signoff


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
