from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from dispatch.packages import dispatch_package
from intake.batches import import_batch
from mirror.acceptance import bootstrap_mirror
from mirror.storage import open_mirror
from publication.drafts import QualityDecision, stage_decisions
from publication.issues import publish_issue
from review.decisions import record_review
from source_store import open_source


DAY = '青溪/2026-11-17'
BATCH = 'Q1-first'
FIRST_REVIEWS = {'R': 'R 的现场记录已核对', 'S': 'S 的现场记录已核对'}


def observations(*pairs, document='Q1 field sheet'):
    return [
        {'row_id': row_id, 'liters': liters,
         'source': {'station': 'Q1', 'document': document, 'line': 101 + position}}
        for position, (row_id, liters) in enumerate(pairs)
    ]


def row_ids(ledger):
    return tuple(row.key.row_id for row in ledger.rows)


class LedgerTestCase(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.source_path = self.directory / 'source.sqlite'
        self.mirror_path = self.directory / 'mirror.sqlite'
        self.source = self.open_source()
        self.mirror = self.open_mirror()

    def open_source(self):
        connection = open_source(self.source_path)
        self.addCleanup(connection.close)
        return connection

    def open_mirror(self, filename=None):
        path = self.mirror_path if filename is None else self.directory / filename
        connection = open_mirror(path)
        self.addCleanup(connection.close)
        return connection

    def reopen_source(self):
        self.source.close()
        self.source = self.open_source()

    def reopen_mirror(self):
        self.mirror.close()
        self.mirror = self.open_mirror()

    def stage(self, **choices):
        return stage_decisions(self.source, DAY,
                               [QualityDecision(row_id, included) for row_id, included in choices.items()])

    def release(self, issue, **choices):
        if choices:
            self.stage(**choices)
        return publish_issue(self.source, DAY, issue)

    def initial_issue(self, *pairs):
        if not pairs:
            pairs = (('R', 7), ('S', 11))
        import_batch(self.source, DAY, BATCH, observations(*pairs))
        return self.release(10, **{row_id: True for row_id, _ in pairs})

    def baseline(self, *pairs):
        return bootstrap_mirror(self.mirror, self.initial_issue(*pairs))

    def review_start(self, connection=None):
        connection = self.mirror if connection is None else connection
        for row_id, decision in FIRST_REVIEWS.items():
            record_review(connection, DAY, 10, row_id, decision)

    def withdrawal_and_return(self):
        middle = self.release(11, R=False)
        target = self.release(12, R=True)
        return middle, target

    def package(self, package_id, start, target):
        return dispatch_package(self.source, package_id, DAY, start, target)

    def receipt_count(self):
        return self.mirror.execute('SELECT COUNT(*) FROM received_packages').fetchone()[0]
