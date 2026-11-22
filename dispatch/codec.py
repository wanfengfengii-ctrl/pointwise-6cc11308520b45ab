from dataclasses import dataclass
import re

from dispatch.evidence import IntervalEvidence
from intake.observations import key_data, key_from_data
from ledger_core import InvalidInput, canonical_json, decimal_text, name, parse_json, read_decimal, require_fields
from publication.projection import DailyProjection, projection_data, projection_from_data


@dataclass(frozen=True)
class V1Package:
    package_id: str
    day: str
    start: int
    target: int
    ledger: DailyProjection
    evidence: IntervalEvidence


def canonical_content(package):
    return canonical_json({
        'version': 1,
        'package_id': package.package_id,
        'day': package.day,
        'start': decimal_text(package.start),
        'target': decimal_text(package.target),
        'ledger': projection_data(package.ledger),
        'evidence': {
            'base_sha256': package.evidence.base_sha256,
            'continuous': [key_data(key) for key in package.evidence.continuous],
        },
    }).encode('utf-8')


def encode_v1(package):
    return canonical_content(package)


def _decode_evidence(value, ledger):
    require_fields(value, {'base_sha256', 'continuous'}, 'interval evidence')
    digest = value['base_sha256']
    if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise InvalidInput('interval evidence is missing a valid base digest')
    if not isinstance(value['continuous'], list):
        raise InvalidInput('continuous keys must be an array')
    keys = tuple(key_from_data(key) for key in value['continuous'])
    key_set = set(keys)
    if keys != tuple(row.key for row in ledger.rows if row.key in key_set):
        raise InvalidInput('continuous keys must be distinct target keys in target order')
    return IntervalEvidence(digest, keys)


def decode_v1(body):
    if not isinstance(body, bytes):
        raise InvalidInput('a V1 package must be UTF-8 bytes')
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise InvalidInput('a V1 package must be UTF-8 bytes') from exc
    value = parse_json(text)
    require_fields(value, {'version', 'package_id', 'day', 'start', 'target', 'ledger', 'evidence'},
                   'V1 envelope')
    if type(value['version']) is not int or value['version'] != 1:
        raise InvalidInput('unsupported package version')
    package_id = name(value['package_id'], 'package id')
    day = name(value['day'], 'day')
    start = read_decimal(value['start'], 'start issue', minimum=1)
    target = read_decimal(value['target'], 'target issue', minimum=1)
    if target <= start:
        raise InvalidInput('package target must follow the starting issue')
    ledger = projection_from_data(value['ledger'])
    if (ledger.day, ledger.issue) != (day, target):
        raise InvalidInput('target ledger does not match the package day and target')
    return V1Package(package_id, day, start, target, ledger, _decode_evidence(value['evidence'], ledger))
