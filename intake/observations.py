from dataclasses import dataclass

from intake.provenance import Provenance, provenance_data, provenance_from_data
from ledger_core import decimal_text, name, read_decimal, require_fields


@dataclass(frozen=True)
class ObservationKey:
    batch_id: str
    row_id: str


@dataclass(frozen=True)
class Observation:
    key: ObservationKey
    batch_order: int
    position: int
    liters: int | None
    source: Provenance


def observation_order(observation):
    return observation.batch_order, observation.position


def key_data(key):
    return {'batch_id': key.batch_id, 'row_id': key.row_id}


def key_from_data(value):
    require_fields(value, {'batch_id', 'row_id'}, 'observation key')
    return ObservationKey(name(value['batch_id'], 'batch id'), name(value['row_id'], 'row id'))


def observation_data(observation):
    liters = observation.liters
    return {
        'key': key_data(observation.key),
        'batch_order': decimal_text(observation.batch_order),
        'position': decimal_text(observation.position),
        'liters': None if liters is None else decimal_text(liters),
        'source': provenance_data(observation.source),
    }


def observation_from_data(value):
    require_fields(value, {'key', 'batch_order', 'position', 'liters', 'source'},
                   'stored observation')
    liters = value['liters']
    if liters is not None:
        liters = read_decimal(liters, 'liters')
    return Observation(
        key_from_data(value['key']),
        read_decimal(value['batch_order'], 'batch order', minimum=1),
        read_decimal(value['position'], 'batch position'),
        liters,
        provenance_from_data(value['source']),
    )
