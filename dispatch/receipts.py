from dispatch.codec import encode_v1


def initialize_dispatch_register(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS dispatched_packages (
            package_id TEXT NOT NULL PRIMARY KEY,
            body BLOB NOT NULL
        )
    ''')


def load_frozen_package(connection, package_id):
    record = connection.execute('SELECT body FROM dispatched_packages WHERE package_id = ?',
                                (package_id,)).fetchone()
    return None if record is None else record[0]


def store_frozen_package(connection, package):
    body = encode_v1(package)
    connection.execute('INSERT INTO dispatched_packages (package_id, body) VALUES (?, ?)',
                       (package.package_id, body))
    return body
