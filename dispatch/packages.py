from dispatch.codec import V1Package, decode_v1
from dispatch.evidence import build_interval_evidence
from dispatch.intervals import load_dispatch_interval
from dispatch.receipts import load_frozen_package, store_frozen_package
from ledger_core import NameConflict, name, whole_number, write_transaction


def dispatch_package(connection, package_id, day, start, target):
    name(package_id, 'package id')
    name(day, 'day')
    whole_number(start, 'start issue', minimum=1)
    whole_number(target, 'target issue', minimum=1)
    with write_transaction(connection):
        frozen = load_frozen_package(connection, package_id)
        if frozen is not None:
            package = decode_v1(frozen)
            if (package.day, package.start, package.target) != (day, start, target):
                raise NameConflict(f'package {package_id!r} is bound to another request')
            return frozen
        interval = load_dispatch_interval(connection, day, start, target)
        package = V1Package(package_id, day, start, target, interval[-1],
                            build_interval_evidence(interval))
        return store_frozen_package(connection, package)
