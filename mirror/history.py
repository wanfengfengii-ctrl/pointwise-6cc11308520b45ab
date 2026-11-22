from dataclasses import dataclass
from hashlib import sha256

from dispatch.codec import V1Package
from ledger_core import NameConflict, decimal_text, name, read_decimal


@dataclass(frozen=True)
class Receipt:
    package_id: str
    day: str
    start: int
    target: int
    content_sha256: str


def _received_record(connection, package_id):
    name(package_id, 'package id')
    return connection.execute('''
        SELECT day, start, target, content FROM received_packages WHERE package_id = ?
    ''', (package_id,)).fetchone()


def _receipt(package_id, day, start, target, content):
    return Receipt(package_id, day, start, target, sha256(content).hexdigest())


def _stored_receipt(package_id, record):
    day, start, target, content = record
    return _receipt(package_id, day, read_decimal(start, 'start issue', minimum=1),
                    read_decimal(target, 'target issue', minimum=1), content)


def find_receipt(connection, package_id):
    record = _received_record(connection, package_id)
    return None if record is None else _stored_receipt(package_id, record)


def match_received_content(connection, package_id, content):
    record = _received_record(connection, package_id)
    if record is None:
        return None
    if record[3] != content:
        raise NameConflict(f'package {package_id!r} has already been received with different content')
    return _stored_receipt(package_id, record)


def store_receipt(connection, package: V1Package, content):
    connection.execute('''
        INSERT INTO received_packages (package_id, day, start, target, content)
        VALUES (?, ?, ?, ?, ?)
    ''', (package.package_id, package.day, decimal_text(package.start),
          decimal_text(package.target), content))
    return _receipt(package.package_id, package.day, package.start, package.target, content)
