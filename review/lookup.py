from ledger_core import MissingRecord, name
from review.storage import load_frozen_signoff


def read_signoff(connection, signoff_id):
    name(signoff_id, 'signoff id')
    signoff = load_frozen_signoff(connection, signoff_id)
    if signoff is None:
        raise MissingRecord(f'unknown signoff {signoff_id!r}')
    return signoff
