from dataclasses import dataclass

from intake.storage import day_has_batch, load_observations
from ledger_core import InvalidInput, MissingRecord, name, write_transaction


@dataclass(frozen=True)
class QualityDecision:
    row_id: str
    included: bool


def load_draft(connection, day):
    name(day, 'day')
    records = connection.execute('''
        SELECT row_id, included FROM quality_drafts WHERE day = ? ORDER BY row_id
    ''', (day,))
    return tuple(QualityDecision(row_id, bool(included)) for row_id, included in records)


def stage_decisions(connection, day, decisions):
    name(day, 'day')
    if not isinstance(decisions, (list, tuple)):
        raise InvalidInput('decisions must be a list or tuple of QualityDecision')
    with write_transaction(connection):
        if not day_has_batch(connection, day):
            raise MissingRecord(f'unknown day {day!r}')
        known = {row.key.row_id for row in load_observations(connection, day)}
        staged = {}
        for decision in decisions:
            if not isinstance(decision, QualityDecision) or type(decision.included) is not bool:
                raise InvalidInput('decisions must be QualityDecision with a boolean inclusion')
            row_id = name(decision.row_id, 'row id')
            if row_id not in known:
                raise MissingRecord(f'row {row_id!r} is unknown for {day!r}')
            if row_id in staged:
                raise InvalidInput(f'duplicate decision for row {row_id!r}')
            staged[row_id] = int(decision.included)
        connection.executemany('''
            INSERT INTO quality_drafts (day, row_id, included) VALUES (?, ?, ?)
            ON CONFLICT (day, row_id) DO UPDATE SET included = excluded.included
        ''', ((day, row_id, included) for row_id, included in staged.items()))
        return load_draft(connection, day)


def clear_draft(connection, day):
    connection.execute('DELETE FROM quality_drafts WHERE day = ?', (day,))
