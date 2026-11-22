from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from ledger_core import InvalidInput, name, whole_number, write_transaction


class ReplyLost(OSError):
    """The device accepted the command, but the caller did not get a reply."""


class Medium:
    def __init__(self, connection):
        self._connection = connection
        header = connection.execute("SELECT medium_id, slot_count FROM medium_header").fetchone()
        if header is None:
            raise InvalidInput("medium has no header")
        self.medium_id, self.slot_count = header
        self._hold_next = False

    def close(self):
        self._connection.close()

    def _slot(self, slot):
        whole_number(slot, "slot")
        if slot >= self.slot_count:
            raise InvalidInput("slot outside this medium")
        return self._connection.execute(
            "SELECT state, body FROM medium_slots WHERE slot = ?", (slot,)
        ).fetchone()

    def status(self, slot):
        return self._slot(slot)[0]

    def read_slot(self, slot):
        return self._slot(slot)[1]

    def hold_next_write(self):
        """Fixture control. Leave the next accepted command in writing and lose its reply."""
        self._hold_next = True

    def write(self, slot, body):
        if type(body) is not bytes or not body:
            raise InvalidInput("slot body must be nonempty bytes")
        held = self._hold_next
        with write_transaction(self._connection):
            if self.status(slot) != "empty":
                raise InvalidInput("cannot write to an occupied slot")
            self._set(slot, "writing" if held else "sealed", body)
        self._hold_next = False
        if held:
            raise ReplyLost("write accepted without a reply")

    def finish(self, slot, outcome):
        """Fixture control. Resolve an accepted write without the original writer."""
        if outcome not in ("sealed", "burned"):
            raise InvalidInput("outcome must be sealed or burned")
        with write_transaction(self._connection):
            state, body = self._slot(slot)
            if state != "writing":
                raise InvalidInput("only a writing slot can finish")
            self._set(slot, outcome, body if outcome == "sealed" else body[:len(body) // 2])

    def damage(self, slot):
        """Fixture control. Simulate a bit error in a sealed slot."""
        with write_transaction(self._connection):
            state, body = self._slot(slot)
            if state != "sealed":
                raise InvalidInput("only a sealed slot can be damaged")
            self._set(slot, state, bytes([body[0] ^ 1]) + body[1:])

    def _set(self, slot, state, body):
        self._connection.execute(
            "UPDATE medium_slots SET state = ?, body = ? WHERE slot = ?", (state, body, slot)
        )


def _initialize(connection, medium_id, slot_count):
    name(medium_id, "medium id")
    whole_number(slot_count, "slot count", minimum=1)
    with write_transaction(connection):
        connection.execute("CREATE TABLE medium_header (medium_id TEXT, slot_count INTEGER)")
        connection.execute("CREATE TABLE medium_slots (slot INTEGER PRIMARY KEY, state TEXT, body BLOB)")
        connection.execute("INSERT INTO medium_header VALUES (?, ?)", (medium_id, slot_count))
        connection.executemany("INSERT INTO medium_slots VALUES (?, ?, NULL)",
                               ((slot, "empty") for slot in range(slot_count)))
    return Medium(connection)


def _connect(path, mode):
    uri = Path(path).resolve().as_uri() + "?mode=" + mode
    return sqlite3.connect(uri, uri=True, isolation_level=None)


def create_medium(path, medium_id, slot_count):
    connection = _connect(path, "rwc")
    try:
        return _initialize(connection, medium_id, slot_count)
    except BaseException:
        connection.close()
        raise


def open_medium(path, *, read_only=False):
    connection = _connect(path, "ro" if read_only else "rw")
    try:
        return Medium(connection)
    except BaseException:
        connection.close()
        raise


class MediumTests(unittest.TestCase):
    def test_lost_reply_then_device_finishes_after_writer_exits(self):
        writer = """from contextlib import closing
import sys
from archive_medium import open_medium, ReplyLost
with closing(open_medium(sys.argv[1])) as device:
    device.hold_next_write()
    try:
        device.write(0, b"opaque-body")
    except ReplyLost:
        sys.exit(0)
sys.exit(1)
"""
        with TemporaryDirectory() as directory:
            for outcome, expected in (("sealed", b"opaque-body"), ("burned", b"opaqu")):
                with self.subTest(outcome=outcome):
                    path = Path(directory) / (outcome + ".sqlite")
                    create_medium(path, outcome, 2).close()
                    subprocess.run([sys.executable, "-B", "-c", writer, str(path)], check=True)
                    with closing(open_medium(path, read_only=True)) as reader:
                        self.assertEqual(reader.medium_id, outcome)
                        self.assertEqual(reader.status(0), "writing")
                        self.assertEqual(reader.read_slot(0), b"opaque-body")
                        self.assertEqual(reader.status(1), "empty")
                        self.assertIsNone(reader.read_slot(1))
                    with closing(open_medium(path)) as device:
                        device.finish(0, outcome)
                        with self.assertRaises(InvalidInput):
                            device.write(0, b"replacement")
                        device.write(1, b"other bytes")
                        device.damage(1)
                    with closing(open_medium(path, read_only=True)) as reader:
                        self.assertEqual((reader.status(0), reader.read_slot(0)), (outcome, expected))
                        self.assertEqual((reader.status(1), reader.read_slot(1)),
                                         ("sealed", b"nther bytes"))


if __name__ == "__main__":
    unittest.main()
