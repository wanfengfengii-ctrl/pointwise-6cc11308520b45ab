from dataclasses import dataclass

from intake.observations import Observation, observation_data, observation_from_data, observation_order
from ledger_core import InvalidInput, decimal_text, name, read_decimal, require_fields, whole_number
from publication.totals import DailyTotals, calculate_totals, totals_data, totals_from_data


@dataclass(frozen=True)
class DailyProjection:
    day: str
    issue: int
    rows: tuple[Observation, ...]
    totals: DailyTotals


def _check_row_identity(rows):
    positions = set()
    row_ids = set()
    order_by_batch = {}
    batch_by_order = {}
    for row in rows:
        position = observation_order(row)
        if row.key.row_id in row_ids or position in positions:
            raise InvalidInput('daily projection repeats a row id or original position')
        row_ids.add(row.key.row_id)
        positions.add(position)
        order = order_by_batch.setdefault(row.key.batch_id, row.batch_order)
        batch = batch_by_order.setdefault(row.batch_order, row.key.batch_id)
        if (order, batch) != (row.batch_order, row.key.batch_id):
            raise InvalidInput('daily projection contains inconsistent batch positions')


def build_projection(day, issue, observations):
    name(day, 'day')
    whole_number(issue, 'issue', minimum=1)
    ordered = tuple(sorted(observations, key=observation_order))
    _check_row_identity(ordered)
    return DailyProjection(day, issue, ordered, calculate_totals(ordered))


def projection_data(projection):
    return {
        'day': projection.day,
        'issue': decimal_text(projection.issue),
        'rows': [observation_data(row) for row in projection.rows],
        'totals': totals_data(projection.totals),
    }


def projection_from_data(value):
    require_fields(value, {'day', 'issue', 'rows', 'totals'}, 'daily projection')
    if not isinstance(value['rows'], list):
        raise InvalidInput('projection rows must be an array')
    rows = tuple(observation_from_data(row) for row in value['rows'])
    issue = read_decimal(value['issue'], 'issue', minimum=1)
    projection = build_projection(value['day'], issue, rows)
    if projection.rows != rows:
        raise InvalidInput('projection rows are out of original order')
    if projection.totals != totals_from_data(value['totals']):
        raise InvalidInput('projection totals do not match the rows')
    return projection
