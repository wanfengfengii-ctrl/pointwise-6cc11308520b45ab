from intake.provenance import Provenance
from ledger_core import MissingRecord, NameConflict, WrongFrontier
from mirror.acceptance import accept_package, bootstrap_mirror
from mirror.frontiers import read_frontier
from mirror.history import find_receipt
from mirror.storage import initialize_mirror_store
from review.decisions import record_review
from review.lookup import read_signoff
from review.signoff import create_signoff
from review.storage import load_current_reviews
from tests.fixtures import DAY, FIRST_REVIEWS, LedgerTestCase, row_ids


class ReviewTests(LedgerTestCase):
    def test_frozen_signoff(self):
        base = self.baseline(('R', 7), ('S', 11), ('M', None))
        self.review_start()
        old = create_signoff(self.mirror, 'old', DAY, 10)
        record_review(self.mirror, DAY, 10, 'M', '现场确认原表缺测')
        self.release(11, R=False, M=False)
        wire = self.package('change', 10, 11)
        self.source.close()
        accept_package(self.mirror, wire)
        self.reopen_mirror()
        again = read_signoff(self.mirror, 'old')
        self.assertEqual(again, old)
        self.assertEqual(again.ledger, base)
        self.assertEqual(row_ids(again.ledger), ('R', 'S', 'M'))
        self.assertEqual(tuple(row.liters for row in again.ledger.rows), (7, 11, None))
        self.assertEqual(again.ledger.rows[2].source, Provenance('Q1', 'Q1 field sheet', 103))
        self.assertEqual((again.ledger.totals.liters, again.ledger.totals.missing), (18, 1))
        self.assertEqual(again.conclusions, (FIRST_REVIEWS['R'], FIRST_REVIEWS['S'], None))
        current = create_signoff(self.mirror, 'new', DAY, 11)
        self.assertEqual(row_ids(current.ledger), ('S',))
        self.assertEqual(current.conclusions, (FIRST_REVIEWS['S'],))
        self.assertEqual((current.ledger.totals.liters, current.ledger.totals.missing), (11, 0))

    def test_stale_review(self):
        self.baseline()
        self.review_start()
        self.withdrawal_and_return()
        wire = self.package('stale-check', 10, 12)
        self.source.close()
        accept_package(self.mirror, wire)
        with self.assertRaises(WrongFrontier):
            record_review(self.mirror, DAY, 10, 'R', 'delayed old conclusion')
        current = create_signoff(self.mirror, 'stale-result', DAY, 12)
        self.assertEqual(current.conclusions, (None, FIRST_REVIEWS['S']))

    def test_ineligible_row(self):
        self.baseline()
        self.review_start()
        self.release(11, R=False)
        wire = self.package('withdrew', 10, 11)
        self.source.close()
        accept_package(self.mirror, wire)
        for row_id in ('R', 'unknown'):
            with self.assertRaises(MissingRecord):
                record_review(self.mirror, DAY, 11, row_id, 'proposed conclusion')
        self.assertEqual(load_current_reviews(self.mirror, DAY, 11), {'S': FIRST_REVIEWS['S']})

    def test_signoff_guard(self):
        self.baseline()
        self.review_start()
        signoff = create_signoff(self.mirror, 'fixed-signoff', DAY, 10)
        record_review(self.mirror, DAY, 10, 'R', '后录现场结论')
        self.assertEqual(create_signoff(self.mirror, 'fixed-signoff', DAY, 10), signoff)
        with self.assertRaises(WrongFrontier):
            create_signoff(self.mirror, 'wrong-issue', DAY, 11)
        self.release(11)
        wire = self.package('next-for-sign', 10, 11)
        self.source.close()
        accept_package(self.mirror, wire)
        with self.assertRaises(NameConflict):
            create_signoff(self.mirror, 'fixed-signoff', DAY, 11)
        self.assertEqual(read_signoff(self.mirror, 'fixed-signoff'), signoff)
        with self.assertRaises(MissingRecord):
            read_signoff(self.mirror, 'wrong-issue')

    def test_unknown_signoff(self):
        self.baseline()
        with self.assertRaises(MissingRecord):
            read_signoff(self.mirror, 'never-signed')

    def test_reinitialize_mirror(self):
        baseline = self.baseline()
        self.review_start()
        self.assertEqual(bootstrap_mirror(self.mirror, baseline), baseline)
        self.assertEqual(load_current_reviews(self.mirror, DAY, 10), FIRST_REVIEWS)
        old = create_signoff(self.mirror, 'first-signoff', DAY, 10)
        self.withdrawal_and_return()
        wire = self.package('next', 10, 12)
        self.source.close()
        receipt = accept_package(self.mirror, wire)
        record_review(self.mirror, DAY, 12, 'R', '新现场结论')
        initialize_mirror_store(self.mirror)
        initialize_mirror_store(self.mirror)
        self.reopen_mirror()
        with self.assertRaises(WrongFrontier):
            bootstrap_mirror(self.mirror, baseline)
        self.assertEqual(read_frontier(self.mirror, DAY), 12)
        self.assertEqual(find_receipt(self.mirror, 'next'), receipt)
        self.assertEqual(load_current_reviews(self.mirror, DAY, 12),
                         {'R': '新现场结论', 'S': FIRST_REVIEWS['S']})
        self.assertEqual(read_signoff(self.mirror, 'first-signoff'), old)
