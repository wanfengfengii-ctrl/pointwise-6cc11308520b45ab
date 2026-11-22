from dataclasses import dataclass

from intake.observations import Observation, ObservationKey
from intake.provenance import Provenance
from ledger_core import decimal_text, read_decimal


@dataclass(frozen=True)
class AcceptedBatch:
    batch_id: str
    day: str
    batch_order: int
    rows: tuple[Observation, ...]


def initialize_intake_store(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS station_batches (
            batch_order INTEGER PRIMARY KEY,
            batch_id TEXT NOT NULL UNIQUE,
            day TEXT NOT NULL,
            UNIQUE (batch_order, day)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS observations (
            day TEXT NOT NULL,
            row_id TEXT NOT NULL,
            batch_order INTEGER NOT NULL,
            position INTEGER NOT NULL,
            liters TEXT,
            station TEXT NOT NULL,
            document TEXT NOT NULL,
            source_line TEXT NOT NULL,
            PRIMARY KEY (batch_order, position),
            UNIQUE (day, row_id),
            FOREIGN KEY (batch_order, day) REFERENCES station_batches (batch_order, day)
        )
    ''')
    connection.execute('''
        CREATE INDEX IF NOT EXISTS station_batches_day ON station_batches (day, batch_order)
    ''')


_SELECT_ROWS = '''
    SELECT b.batch_id, o.row_id, o.batch_order, o.position, o.liters,
           o.station, o.document, o.source_line
    FROM observations AS o
    JOIN station_batches AS b ON b.batch_order = o.batch_order
'''


def _read_observation(record):
    batch_id, row_id, order, position, liters, station, document, source_line = record
    source = Provenance(station, document, read_decimal(source_line, 'source line', minimum=1))
    reading = None if liters is None else read_decimal(liters, 'liters')
    return Observation(ObservationKey(batch_id, row_id), order, position, reading, source)


def load_batch(connection, batch_id):
    record = connection.execute('''
        SELECT day, batch_order FROM station_batches WHERE batch_id = ?
    ''', (batch_id,)).fetchone()
    if record is None:
        return None
    day, batch_order = record
    rows = connection.execute(_SELECT_ROWS + '''
        WHERE o.batch_order = ? ORDER BY o.position
    ''', (batch_order,))
    return AcceptedBatch(batch_id, day, batch_order, tuple(map(_read_observation, rows)))


def load_observations(connection, day):
    rows = connection.execute(_SELECT_ROWS + '''
        WHERE o.day = ? ORDER BY o.batch_order, o.position
    ''', (day,))
    return tuple(map(_read_observation, rows))


def day_has_batch(connection, day):
    return connection.execute('SELECT 1 FROM station_batches WHERE day = ? LIMIT 1',
                              (day,)).fetchone() is not None


def store_batch(connection, day, batch_id, rows):
    cursor = connection.execute('INSERT INTO station_batches (batch_id, day) VALUES (?, ?)',
                                (batch_id, day))
    batch_order = cursor.lastrowid
    observations = tuple(Observation(row.key, batch_order, position, row.liters, row.source)
                         for position, row in enumerate(rows))
    connection.executemany('''
        INSERT INTO observations
            (day, row_id, batch_order, position, liters, station, document, source_line)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', ((day, row.key.row_id, row.batch_order, row.position,
           None if row.liters is None else decimal_text(row.liters),
           row.source.station, row.source.document, decimal_text(row.source.line))
          for row in observations))
    return AcceptedBatch(batch_id, day, batch_order, observations)
