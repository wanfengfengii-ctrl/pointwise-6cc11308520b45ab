from dataclasses import dataclass

from ledger_core import decimal_text, name, read_decimal, require_fields, whole_number


@dataclass(frozen=True)
class Provenance:
    station: str
    document: str
    line: int


def capture_provenance(value):
    require_fields(value, {'station', 'document', 'line'}, 'provenance')
    return Provenance(name(value['station'], 'station'),
                      name(value['document'], 'source document'),
                      whole_number(value['line'], 'source line', minimum=1))


def provenance_data(source):
    return {'station': source.station, 'document': source.document,
            'line': decimal_text(source.line)}


def provenance_from_data(value):
    require_fields(value, {'station', 'document', 'line'}, 'stored provenance')
    line = read_decimal(value['line'], 'source line', minimum=1)
    return capture_provenance({**value, 'line': line})
