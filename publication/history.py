from ledger_core import MissingRecord, canonical_json, decimal_text, name, parse_json, whole_number
from publication.projection import projection_data, projection_from_data


def initialize_publication_store(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS quality_drafts (
            day TEXT NOT NULL,
            row_id TEXT NOT NULL,
            included INTEGER NOT NULL CHECK (included IN (0, 1)),
            PRIMARY KEY (day, row_id),
            FOREIGN KEY (day, row_id) REFERENCES observations (day, row_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS official_issues (
            day TEXT NOT NULL,
            issue TEXT NOT NULL,
            projection TEXT NOT NULL,
            PRIMARY KEY (day, issue)
        )
    ''')


def _from_record(record):
    return projection_from_data(parse_json(record[0]))


def read_issue(connection, day, issue):
    name(day, 'day')
    issue_key = decimal_text(whole_number(issue, 'issue', minimum=1))
    record = connection.execute('''
        SELECT projection FROM official_issues WHERE day = ? AND issue = ?
    ''', (day, issue_key)).fetchone()
    if record is None:
        raise MissingRecord(f'unknown official issue {issue_key} for {day!r}')
    return _from_record(record)


def read_head_issue(connection, day):
    name(day, 'day')
    record = connection.execute('''
        SELECT projection FROM official_issues WHERE day = ?
        ORDER BY length(issue) DESC, issue DESC LIMIT 1
    ''', (day,)).fetchone()
    return None if record is None else _from_record(record)


def read_official_interval(connection, day, start, target):
    name(day, 'day')
    first = decimal_text(whole_number(start, 'start issue', minimum=1))
    last = decimal_text(whole_number(target, 'target issue', minimum=1))
    records = connection.execute('''
        SELECT projection FROM official_issues WHERE day = ?
        AND (length(issue), issue) >= (?, ?) AND (length(issue), issue) <= (?, ?)
        ORDER BY length(issue), issue
    ''', (day, len(first), first, len(last), last))
    return tuple(map(_from_record, records))


def store_issue(connection, projection):
    connection.execute('''
        INSERT INTO official_issues (day, issue, projection) VALUES (?, ?, ?)
    ''', (projection.day, decimal_text(projection.issue), canonical_json(projection_data(projection))))
