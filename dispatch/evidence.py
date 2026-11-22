from dataclasses import dataclass
from hashlib import sha256

from intake.observations import ObservationKey
from ledger_core import InvalidInput, canonical_json
from publication.projection import projection_data


@dataclass(frozen=True)
class IntervalEvidence:
    base_sha256: str
    continuous: tuple[ObservationKey, ...]


def projection_digest(projection):
    encoded = canonical_json(projection_data(projection)).encode('utf-8')
    return sha256(encoded).hexdigest()


def build_interval_evidence(interval):
    if len(interval) < 2:
        raise InvalidInput('interval evidence requires a starting and a target issue')
    first = interval[0]
    keep = {row.key for row in first.rows}
    previous_issue = first.issue
    for issue in interval[1:]:
        if issue.day != first.day or issue.issue <= previous_issue:
            raise InvalidInput('interval evidence requires ordered issues of one day')
        keep.intersection_update(row.key for row in issue.rows)
        previous_issue = issue.issue
    ordered = tuple(row.key for row in interval[-1].rows if row.key in keep)
    return IntervalEvidence(projection_digest(first), ordered)
