"""Cold-archive item byte format shared by archiving and cold read-back.

A sealed slot body is ``sha256(payload) || ':' || payload`` where the payload is
canonical JSON carrying the archive identity and the whole frozen signoff. The
digest therefore covers both the archive identity and the entire signoff body,
so a cold reader can verify them from the medium alone.
"""
import hashlib

from ledger_core import InvalidInput, canonical_json, name, parse_json, require_fields
from publication.projection import projection_data, projection_from_data
from review.storage import FrozenSignoff

FORMAT = 'qingxi-cold-archive/v1'
_DIGEST_LEN = 64
_SEPARATOR = b':'


def encode_item(archive_id, signoff):
    """Serialize one frozen signoff into self-checking cold-archive bytes."""
    payload = canonical_json({
        'format': FORMAT,
        'archive_id': name(archive_id, 'archive id'),
        'signoff_id': signoff.signoff_id,
        'ledger': projection_data(signoff.ledger),
        'conclusions': list(signoff.conclusions),
    }).encode('utf-8')
    return hashlib.sha256(payload).hexdigest().encode('ascii') + _SEPARATOR + payload


def _signoff_from_data(data):
    require_fields(data, {'format', 'archive_id', 'signoff_id', 'ledger', 'conclusions'},
                   'cold archive item')
    if data['format'] != FORMAT:
        raise InvalidInput('unknown cold archive format')
    archive_id = name(data['archive_id'], 'archive id')
    signoff_id = name(data['signoff_id'], 'signoff id')
    ledger = projection_from_data(data['ledger'])
    conclusions = data['conclusions']
    if not isinstance(conclusions, list) or len(conclusions) != len(ledger.rows):
        raise InvalidInput('archived conclusions do not match signed rows')
    checked = tuple(None if item is None else name(item, 'conclusion')
                    for item in conclusions)
    return archive_id, FrozenSignoff(signoff_id, ledger, checked)


def parse_item(body):
    """Parse cold medium bytes.

    Returns ``('ok', archive_id, signoff)`` for an intact item,
    ``('damaged', claimed_archive_id, None)`` for a recognizable item that fails
    its integrity check, and ``('foreign', None, None)`` for bytes that are not
    a recognizable cold-archive item.
    """
    if (not isinstance(body, bytes) or len(body) <= _DIGEST_LEN
            or body[_DIGEST_LEN:_DIGEST_LEN + 1] != _SEPARATOR):
        return 'foreign', None, None
    digest = body[:_DIGEST_LEN]
    payload = body[_DIGEST_LEN + 1:]
    try:
        data = parse_json(payload.decode('utf-8'))
    except (InvalidInput, UnicodeDecodeError):
        return 'foreign', None, None
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        return 'foreign', None, None
    claimed = data.get('archive_id')
    claimed = claimed if isinstance(claimed, str) else None
    if hashlib.sha256(payload).hexdigest().encode('ascii') != digest:
        return 'damaged', claimed, None
    try:
        archive_id, signoff = _signoff_from_data(data)
    except InvalidInput:
        return 'damaged', claimed, None
    return 'ok', archive_id, signoff
