from dispatch.receipts import initialize_dispatch_register
from intake.storage import initialize_intake_store
from ledger_core import open_database, write_transaction
from publication.history import initialize_publication_store


def initialize_source(connection):
    with write_transaction(connection):
        initialize_intake_store(connection)
        initialize_publication_store(connection)
        initialize_dispatch_register(connection)


def open_source(path):
    connection = open_database(path)
    try:
        initialize_source(connection)
    except BaseException:
        connection.close()
        raise
    return connection
