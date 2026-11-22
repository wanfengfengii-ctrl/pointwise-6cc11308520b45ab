import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal


class LedgerError(ValueError):
    pass


class InvalidInput(LedgerError):
    pass


class MissingRecord(LedgerError):
    pass


class NameConflict(LedgerError):
    pass


class WrongFrontier(LedgerError):
    pass


def name(value, label):
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f'{label} must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise InvalidInput(f'{label} must be valid UTF-8 text') from exc
    return value


def whole_number(value, label, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise InvalidInput(f'{label} must be an integer of at least {minimum}')
    return value


def decimal_text(value):
    whole_number(value, 'integer')
    return format(Decimal(value), 'f')


def read_decimal(value, label, *, minimum=0):
    if (not isinstance(value, str) or not value.isascii() or not value.isdigit()
            or (len(value) > 1 and value.startswith('0'))):
        raise InvalidInput(f'{label} must be an unsigned canonical decimal string')
    return whole_number(int(Decimal(value)), label, minimum=minimum)


def require_fields(value, fields, label):
    if not isinstance(value, dict) or value.keys() != fields:
        raise InvalidInput(f'{label} has unexpected or missing fields')


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _reject_json_constant(token):
    raise InvalidInput(f'invalid JSON constant {token}')


def parse_json(text):
    try:
        return json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=_reject_json_constant)
    except InvalidInput:
        raise
    except (ValueError, RecursionError) as exc:
        raise InvalidInput('invalid JSON document') from exc


def open_database(path):
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def write_transaction(connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
