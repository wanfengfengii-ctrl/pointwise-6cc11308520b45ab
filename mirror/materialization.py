from ledger_core import MissingRecord, canonical_json, decimal_text, name, parse_json, whole_number
from mirror.frontiers import read_frontier
from publication.projection import projection_data, projection_from_data


def materialize_target(connection, projection):
    data = projection_data(projection)
    checked = projection_from_data(data)
    connection.execute('''
        INSERT INTO received_ledgers (day, issue, projection) VALUES (?, ?, ?)
    ''', (checked.day, decimal_text(checked.issue), canonical_json(data)))


def read_received_ledger(connection, day, issue):
    name(day, 'day')
    issue_key = decimal_text(whole_number(issue, 'issue', minimum=1))
    record = connection.execute('''
        SELECT projection FROM received_ledgers WHERE day = ? AND issue = ?
    ''', (day, issue_key)).fetchone()
    if record is None:
        raise MissingRecord(f'no received ledger for {day!r} at issue {issue_key}')
    return projection_from_data(parse_json(record[0]))


def read_current_ledger(connection, day):
    issue = read_frontier(connection, day)
    if issue is None:
        raise MissingRecord(f'no received ledger for {day!r}')
    return read_received_ledger(connection, day, issue)
