from dataclasses import dataclass

from ledger_core import InvalidInput, canonical_json, decimal_text, name, parse_json, require_fields
from publication.projection import DailyProjection, projection_data, projection_from_data


@dataclass(frozen=True)
class FrozenSignoff:
    signoff_id: str
    ledger: DailyProjection
    conclusions: tuple[str | None, ...]

    @property
    def states(self):
        return tuple('pending' if decision is None else 'reviewed' for decision in self.conclusions)


def initialize_review_store(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS effective_reviews (
            day TEXT NOT NULL,
            issue TEXT NOT NULL,
            row_id TEXT NOT NULL,
            conclusion TEXT NOT NULL,
            PRIMARY KEY (day, row_id),
            FOREIGN KEY (day, issue) REFERENCES received_ledgers (day, issue)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS frozen_signoffs (
            signoff_id TEXT NOT NULL PRIMARY KEY,
            content TEXT NOT NULL
        )
    ''')


def load_current_reviews(connection, day, issue):
    records = connection.execute('''
        SELECT row_id, conclusion FROM effective_reviews WHERE day = ? AND issue = ?
    ''', (day, decimal_text(issue)))
    return dict(records)


def store_current_review(connection, day, issue, row_id, conclusion):
    connection.execute('''
        INSERT INTO effective_reviews (day, issue, row_id, conclusion) VALUES (?, ?, ?, ?)
        ON CONFLICT (day, row_id) DO UPDATE SET
            issue = excluded.issue, conclusion = excluded.conclusion
    ''', (day, decimal_text(issue), row_id, conclusion))


def replace_effective_reviews(connection, day, issue, reviews):
    issue_key = decimal_text(issue)
    connection.execute('DELETE FROM effective_reviews WHERE day = ?', (day,))
    connection.executemany('''
        INSERT INTO effective_reviews (day, issue, row_id, conclusion) VALUES (?, ?, ?, ?)
    ''', ((day, issue_key, row_id, conclusion) for row_id, conclusion in reviews.items()))


def load_frozen_signoff(connection, signoff_id):
    record = connection.execute('SELECT content FROM frozen_signoffs WHERE signoff_id = ?',
                                (signoff_id,)).fetchone()
    if record is None:
        return None
    content = parse_json(record[0])
    require_fields(content, {'ledger', 'conclusions'}, 'frozen signoff')
    ledger = projection_from_data(content['ledger'])
    conclusions = content['conclusions']
    if not isinstance(conclusions, list) or len(conclusions) != len(ledger.rows):
        raise InvalidInput('frozen conclusions do not match signed rows')
    return FrozenSignoff(signoff_id, ledger,
                         tuple(None if item is None else name(item, 'conclusion')
                               for item in conclusions))


def store_signoff(connection, signoff):
    content = canonical_json({
        'ledger': projection_data(signoff.ledger),
        'conclusions': signoff.conclusions,
    })
    connection.execute('INSERT INTO frozen_signoffs (signoff_id, content) VALUES (?, ?)',
                       (signoff.signoff_id, content))
