from ledger_core import MissingRecord, name
from mirror.frontiers import require_frontier
from mirror.materialization import read_received_ledger
from mirror.storage import mirror_transaction
from review.storage import store_current_review


def record_review(connection, day, issue, row_id, conclusion):
    name(row_id, 'row id')
    name(conclusion, 'conclusion')
    with mirror_transaction(connection):
        require_frontier(connection, day, issue)
        ledger = read_received_ledger(connection, day, issue)
        if all(row.key.row_id != row_id for row in ledger.rows):
            raise MissingRecord(f'row {row_id!r} is absent from the current received issue')
        store_current_review(connection, day, issue, row_id, conclusion)
        return conclusion
