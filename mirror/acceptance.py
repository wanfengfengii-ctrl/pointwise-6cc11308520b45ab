from dispatch.codec import canonical_content, decode_v1
from dispatch.evidence import projection_digest
from ledger_core import InvalidInput, WrongFrontier
from mirror.frontiers import advance_frontier, read_frontier, require_frontier
from mirror.history import match_received_content, store_receipt
from mirror.materialization import materialize_target, read_received_ledger
from mirror.storage import mirror_transaction
from review.eligibility import apply_review_eligibility


def bootstrap_mirror(connection, baseline):
    with mirror_transaction(connection):
        current = read_frontier(connection, baseline.day)
        if current is not None:
            if current == baseline.issue:
                existing = read_received_ledger(connection, baseline.day, current)
                if existing == baseline:
                    return existing
            raise WrongFrontier('the day already has a different received ledger')
        materialize_target(connection, baseline)
        advance_frontier(connection, baseline.day, baseline.issue)
        return baseline


def _check_starting_ledger(package, starting_ledger):
    if package.evidence.base_sha256 != projection_digest(starting_ledger):
        raise InvalidInput('package evidence belongs to a different starting ledger')
    starting_rows = {row.key.row_id: row for row in starting_ledger.rows}
    for row in package.ledger.rows:
        previous = starting_rows.get(row.key.row_id)
        if previous is not None and previous != row:
            raise InvalidInput(f'original observation {row.key.row_id!r} changed across the handoff')
    starting_keys = {row.key for row in starting_ledger.rows}
    if not starting_keys.issuperset(package.evidence.continuous):
        raise InvalidInput('continuous keys must also belong to the starting ledger')


def accept_package(connection, body, *, before_commit=None):
    package = decode_v1(body)
    content = canonical_content(package)
    with mirror_transaction(connection):
        existing = match_received_content(connection, package.package_id, content)
        if existing is not None:
            return existing
        require_frontier(connection, package.day, package.start)
        starting_ledger = read_received_ledger(connection, package.day, package.start)
        _check_starting_ledger(package, starting_ledger)
        materialize_target(connection, package.ledger)
        apply_review_eligibility(connection, starting_ledger, package.ledger, package.evidence)
        advance_frontier(connection, package.day, package.target)
        receipt = store_receipt(connection, package, content)
        if before_commit is not None:
            before_commit()
        return receipt
