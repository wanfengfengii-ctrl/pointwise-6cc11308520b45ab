from ledger_core import open_database, write_transaction
from review.storage import initialize_review_store


mirror_transaction = write_transaction


def initialize_mirror_store(connection):
    with mirror_transaction(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS received_ledgers (
                day TEXT NOT NULL,
                issue TEXT NOT NULL,
                projection TEXT NOT NULL,
                PRIMARY KEY (day, issue)
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS mirror_frontiers (
                day TEXT NOT NULL PRIMARY KEY,
                issue TEXT NOT NULL,
                FOREIGN KEY (day, issue) REFERENCES received_ledgers (day, issue)
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS received_packages (
                package_id TEXT NOT NULL PRIMARY KEY,
                day TEXT NOT NULL,
                start TEXT NOT NULL,
                target TEXT NOT NULL,
                content BLOB NOT NULL,
                FOREIGN KEY (day, start) REFERENCES received_ledgers (day, issue),
                FOREIGN KEY (day, target) REFERENCES received_ledgers (day, issue)
            )
        ''')
        initialize_review_store(connection)


def open_mirror(path):
    connection = open_database(path)
    try:
        initialize_mirror_store(connection)
    except BaseException:
        connection.close()
        raise
    return connection
