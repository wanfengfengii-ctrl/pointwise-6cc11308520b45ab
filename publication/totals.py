from dataclasses import dataclass

from ledger_core import decimal_text, read_decimal, require_fields


@dataclass(frozen=True)
class DailyTotals:
    liters: int
    missing: int


def calculate_totals(observations):
    liters = 0
    missing = 0
    for observation in observations:
        if observation.liters is None:
            missing += 1
        else:
            liters += observation.liters
    return DailyTotals(liters, missing)


def totals_data(totals):
    return {'liters': decimal_text(totals.liters), 'missing': decimal_text(totals.missing)}


def totals_from_data(value):
    require_fields(value, {'liters', 'missing'}, 'daily totals')
    return DailyTotals(read_decimal(value['liters'], 'total liters'),
                       read_decimal(value['missing'], 'missing count'))
