from dispatch.codec import decode_v1
from intake.batches import get_batch, import_batch
from intake.provenance import Provenance
from intake.storage import load_observations
from ledger_core import InvalidInput, MissingRecord, NameConflict
from publication.drafts import QualityDecision, load_draft, stage_decisions
from publication.history import read_head_issue, read_issue
from publication.issues import publish_issue
from source_store import initialize_source
from tests.fixtures import BATCH, DAY, LedgerTestCase, observations, row_ids


class DailyTests(LedgerTestCase):
    def test_official_totals(self):
        ledger = self.initial_issue(('R', 7), ('S', 11), ('Z', 0), ('M', None))
        self.assertEqual(row_ids(ledger), ('R', 'S', 'Z', 'M'))
        self.assertEqual(tuple(row.liters for row in ledger.rows), (7, 11, 0, None))
        self.assertEqual(tuple(row.position for row in ledger.rows), (0, 1, 2, 3))
        self.assertEqual(tuple(row.source for row in ledger.rows),
                         tuple(Provenance('Q1', 'Q1 field sheet', n) for n in (101, 102, 103, 104)))
        self.assertEqual((ledger.totals.liters, ledger.totals.missing), (18, 1))
        initialize_source(self.source)
        self.reopen_source()
        self.assertEqual(read_issue(self.source, DAY, 10), ledger)
        self.assertEqual(get_batch(self.source, BATCH).rows, ledger.rows)

    def test_batch_retry(self):
        rows = observations(('S', 7), ('R', 7))
        first = import_batch(self.source, DAY, BATCH, rows)
        self.reopen_source()
        self.assertEqual(import_batch(self.source, DAY, BATCH, rows), first)
        later = import_batch(self.source, DAY, 'later', observations(('A', 7), document='Q1 addendum'))
        ledger = self.release(10, A=True, R=True, S=True)
        self.assertEqual(row_ids(ledger), ('S', 'R', 'A'))
        self.assertEqual(ledger.rows, first.rows + later.rows)
        self.assertEqual([row.source.document for row in ledger.rows],
                         ['Q1 field sheet', 'Q1 field sheet', 'Q1 addendum'])
        self.assertEqual((ledger.totals.liters, ledger.totals.missing), (21, 0))

    def test_zero_is_reading(self):
        big = 10 ** 4600 + 7
        baseline = self.initial_issue(('R', big), ('S', 11), ('Z', 0), ('M', None))
        target = self.release(100)
        item = decode_v1(self.package('precise', 10, 100))
        for ledger in (baseline, target, item.ledger):
            self.assertEqual(ledger.rows[0].liters, big)
            self.assertEqual((ledger.rows[2].liters, ledger.rows[3].liters), (0, None))
            self.assertEqual((ledger.totals.liters, ledger.totals.missing), (big + 11, 1))
        self.assertEqual(item.ledger, target)

    def test_point_in_time(self):
        original = self.initial_issue(('R', 7), ('S', 11), ('M', None))
        self.stage(R=False, M=False)
        self.assertEqual(read_head_issue(self.source, DAY), original)
        newer = self.release(11)
        self.assertEqual(row_ids(newer), ('S',))
        self.assertEqual(newer.rows[0].source, Provenance('Q1', 'Q1 field sheet', 102))
        empty = self.release(12, S=False)
        self.assertEqual(row_ids(empty), ())
        self.assertEqual((empty.totals.liters, empty.totals.missing), (0, 0))
        self.assertEqual(read_issue(self.source, DAY, 10), original)
        self.assertEqual((original.totals.liters, original.totals.missing), (18, 1))
        with self.assertRaises(InvalidInput):
            self.release(11)
        self.assertEqual(read_head_issue(self.source, DAY), empty)

    def test_publish_rollback(self):
        original = self.initial_issue()
        draft = self.stage(R=False)

        def fail_before_commit():
            self.assertEqual(row_ids(read_issue(self.source, DAY, 11)), ('S',))
            self.assertEqual(load_draft(self.source, DAY), ())
            raise RuntimeError('publish commit interrupted')

        with self.assertRaisesRegex(RuntimeError, 'publish commit interrupted'):
            publish_issue(self.source, DAY, 11, before_commit=fail_before_commit)
        self.reopen_source()
        self.assertEqual(read_head_issue(self.source, DAY), original)
        self.assertEqual(load_draft(self.source, DAY), draft)
        with self.assertRaises(MissingRecord):
            read_issue(self.source, DAY, 11)
        self.assertEqual(row_ids(self.release(11)), ('S',))
        self.assertEqual(read_issue(self.source, DAY, 10), original)

    def test_reinitialize(self):
        original = self.initial_issue()
        self.stage(R=False, S=False)
        changed = self.stage(R=True)
        raw = get_batch(self.source, BATCH)
        initialize_source(self.source)
        initialize_source(self.source)
        self.reopen_source()
        self.assertEqual(load_draft(self.source, DAY), changed)
        self.assertEqual(read_head_issue(self.source, DAY), original)
        self.assertEqual(get_batch(self.source, BATCH), raw)
        self.assertEqual(row_ids(self.release(11)), ('R',))

    def test_bad_batch(self):
        original = self.initial_issue()
        for invalid in (-1, True, 1.5, '9'):
            with self.subTest(invalid=invalid):
                rows = observations(('A', 5), ('B', invalid), document='unaccepted sheet')
                with self.assertRaises(InvalidInput):
                    import_batch(self.source, DAY, 'bad', rows)
        self.reopen_source()
        with self.assertRaises(MissingRecord):
            get_batch(self.source, 'bad')
        self.assertEqual(load_observations(self.source, DAY), original.rows)
        self.assertEqual(read_head_issue(self.source, DAY), original)

    def test_batch_conflict(self):
        original = self.initial_issue()
        accepted = get_batch(self.source, BATCH)
        different_rows = [observations(('R', 7), ('S', 12)),
                          observations(('S', 11), ('R', 7)),
                          observations(('R', 7), ('S', 11), document='different source')]
        for rows in different_rows:
            with self.assertRaises(NameConflict):
                import_batch(self.source, DAY, BATCH, rows)
        with self.assertRaises(NameConflict):
            import_batch(self.source, '青溪/other', BATCH, observations(('R', 7), ('S', 11)))
        with self.assertRaises(NameConflict):
            import_batch(self.source, DAY, 'new', observations(('X', 2), ('R', 7)))
        self.assertEqual(get_batch(self.source, BATCH), accepted)
        self.assertEqual(load_observations(self.source, DAY), original.rows)
        self.assertEqual(read_head_issue(self.source, DAY), original)

    def test_unknown_draft_row(self):
        original = self.initial_issue()
        previous_draft = self.stage(R=False)
        other_day = '北支/2026-11-17'
        import_batch(self.source, other_day, 'other-batch', observations(('X', 4)))
        with self.assertRaises(MissingRecord):
            stage_decisions(self.source, DAY, [QualityDecision('R', True), QualityDecision('X', True)])
        self.assertEqual(load_draft(self.source, DAY), previous_draft)
        self.assertEqual(read_head_issue(self.source, DAY), original)
        self.assertEqual(row_ids(self.release(11)), ('S',))
