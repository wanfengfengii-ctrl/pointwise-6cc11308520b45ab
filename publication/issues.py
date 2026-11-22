from intake.storage import day_has_batch, load_observations
from ledger_core import InvalidInput, MissingRecord, name, whole_number, write_transaction
from publication.drafts import clear_draft, load_draft
from publication.history import read_head_issue, store_issue
from publication.projection import build_projection


def publish_issue(connection, day, issue, *, before_commit=None):
    name(day, 'day')
    whole_number(issue, 'issue', minimum=1)
    with write_transaction(connection):
        if not day_has_batch(connection, day):
            raise MissingRecord(f'unknown day {day!r}')
        previous = read_head_issue(connection, day)
        if previous is not None and issue <= previous.issue:
            raise InvalidInput('the new official issue must follow the current issue')
        included = set() if previous is None else {row.key.row_id for row in previous.rows}
        observations = load_observations(connection, day)
        known = {row.key.row_id for row in observations}
        for decision in load_draft(connection, day):
            if decision.row_id not in known:
                raise MissingRecord(f'draft has unknown row {decision.row_id!r}')
            if decision.included:
                included.add(decision.row_id)
            else:
                included.discard(decision.row_id)
        projection = build_projection(day, issue,
                                      (row for row in observations if row.key.row_id in included))
        store_issue(connection, projection)
        clear_draft(connection, day)
        if before_commit is not None:
            before_commit()
        return projection
