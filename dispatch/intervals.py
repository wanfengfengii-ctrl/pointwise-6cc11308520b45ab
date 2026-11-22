from ledger_core import InvalidInput, MissingRecord, whole_number
from publication.history import read_official_interval


def load_dispatch_interval(connection, day, start, target):
    whole_number(start, 'start issue', minimum=1)
    whole_number(target, 'target issue', minimum=1)
    if target <= start:
        raise InvalidInput('dispatch target must follow its starting issue')
    interval = read_official_interval(connection, day, start, target)
    if not interval or interval[0].issue != start or interval[-1].issue != target:
        raise MissingRecord('both dispatch endpoints must be official issues of this day')
    return interval
