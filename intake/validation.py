from dataclasses import dataclass

from intake.observations import ObservationKey
from intake.provenance import Provenance, capture_provenance
from ledger_core import InvalidInput, name, require_fields, whole_number


@dataclass(frozen=True)
class BatchRow:
    key: ObservationKey
    liters: int | None
    source: Provenance


def validate_batch(batch_id, rows):
    name(batch_id, 'batch id')
    if not isinstance(rows, (list, tuple)):
        raise InvalidInput('batch rows must be an ordered list or tuple')
    validated = []
    seen = set()
    for row in rows:
        require_fields(row, {'row_id', 'liters', 'source'}, 'batch row')
        row_id = name(row['row_id'], 'row id')
        if row_id in seen:
            raise InvalidInput(f'duplicate batch row {row_id!r}')
        seen.add(row_id)
        liters = row['liters']
        if liters is not None:
            whole_number(liters, 'liters')
        validated.append(BatchRow(ObservationKey(batch_id, row_id), liters,
                                  capture_provenance(row['source'])))
    return tuple(validated)
