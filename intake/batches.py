from intake.storage import load_batch, load_observations, store_batch
from intake.validation import BatchRow, validate_batch
from ledger_core import NameConflict, MissingRecord, name, write_transaction


def import_batch(connection, day, batch_id, rows):
    name(day, 'day')
    incoming = validate_batch(batch_id, rows)
    with write_transaction(connection):
        existing = load_batch(connection, batch_id)
        if existing is not None:
            original = tuple(BatchRow(row.key, row.liters, row.source) for row in existing.rows)
            if (existing.day, original) != (day, incoming):
                raise NameConflict(f'batch {batch_id!r} is already registered with different data')
            return existing

        used_ids = {row.key.row_id for row in load_observations(connection, day)}
        for row in incoming:
            if row.key.row_id in used_ids:
                raise NameConflict(f'row {row.key.row_id!r} is already registered for this day')
        return store_batch(connection, day, batch_id, incoming)


def get_batch(connection, batch_id):
    name(batch_id, 'batch id')
    batch = load_batch(connection, batch_id)
    if batch is None:
        raise MissingRecord(f'unknown batch {batch_id!r}')
    return batch
