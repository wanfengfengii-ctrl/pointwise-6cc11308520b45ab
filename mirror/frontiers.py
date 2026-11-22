from ledger_core import WrongFrontier, decimal_text, name, read_decimal, whole_number


def read_frontier(connection, day):
    name(day, 'day')
    record = connection.execute('SELECT issue FROM mirror_frontiers WHERE day = ?',
                                (day,)).fetchone()
    return None if record is None else read_decimal(record[0], 'frontier', minimum=1)


def require_frontier(connection, day, expected):
    whole_number(expected, 'expected issue', minimum=1)
    actual = read_frontier(connection, day)
    if actual != expected:
        description = 'uninitialized' if actual is None else decimal_text(actual)
        raise WrongFrontier(f'{day!r} is at {description}, expected {decimal_text(expected)}')
    return actual


def advance_frontier(connection, day, target):
    target_key = decimal_text(whole_number(target, 'target issue', minimum=1))
    current = read_frontier(connection, day)
    if current is not None and current >= target:
        raise WrongFrontier('target must follow the current mirror frontier')
    connection.execute('''
        INSERT INTO mirror_frontiers (day, issue) VALUES (?, ?)
        ON CONFLICT (day) DO UPDATE SET issue = excluded.issue
    ''', (day, target_key))
