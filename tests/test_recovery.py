import json
from dataclasses import replace

from dispatch.codec import decode_v1, encode_v1
from ledger_core import MissingRecord, NameConflict, WrongFrontier
from mirror.acceptance import accept_package
from mirror.frontiers import read_frontier
from mirror.history import find_receipt
from mirror.materialization import read_current_ledger, read_received_ledger
from review.decisions import record_review
from review.lookup import read_signoff
from review.signoff import create_signoff
from review.storage import load_current_reviews
from tests.fixtures import DAY, FIRST_REVIEWS, LedgerTestCase


class RecoveryTests(LedgerTestCase):
    def test_commit_failure(self):
        initial = self.baseline()
        self.review_start()
        original = create_signoff(self.mirror, 'before-failure', DAY, 10)
        _, target = self.withdrawal_and_return()
        wire = self.package('recovery', 10, 12)
        self.source.close()
        observer = self.open_mirror()

        def fail_before_commit():
            self.assertEqual(read_current_ledger(self.mirror, DAY), target)
            self.assertEqual(load_current_reviews(self.mirror, DAY, 12), {'S': FIRST_REVIEWS['S']})
            self.assertEqual(find_receipt(self.mirror, 'recovery').target, 12)
            self.assertEqual(read_current_ledger(observer, DAY), initial)
            self.assertIsNone(find_receipt(observer, 'recovery'))
            raise RuntimeError('mirror commit interrupted')

        with self.assertRaisesRegex(RuntimeError, 'mirror commit interrupted'):
            accept_package(self.mirror, wire, before_commit=fail_before_commit)
        observer.close()
        self.reopen_mirror()
        self.assertEqual(read_frontier(self.mirror, DAY), 10)
        self.assertEqual(read_current_ledger(self.mirror, DAY), initial)
        self.assertEqual(load_current_reviews(self.mirror, DAY, 10), FIRST_REVIEWS)
        self.assertIsNone(find_receipt(self.mirror, 'recovery'))
        self.assertEqual(self.receipt_count(), 0)
        with self.assertRaises(MissingRecord):
            read_received_ledger(self.mirror, DAY, 12)
        receipt = accept_package(self.mirror, wire)
        self.assertEqual(receipt.target, 12)
        self.assertEqual(find_receipt(self.mirror, 'recovery'), receipt)
        self.assertEqual(self.receipt_count(), 1)
        self.assertEqual(read_current_ledger(self.mirror, DAY), target)
        self.assertEqual(load_current_reviews(self.mirror, DAY, 12), {'S': FIRST_REVIEWS['S']})
        self.assertEqual(read_signoff(self.mirror, 'before-failure'), original)
        self.assertEqual(accept_package(self.mirror, wire), receipt)
        self.assertEqual(self.receipt_count(), 1)

    def test_retry_and_late(self):
        self.baseline()
        self.review_start()
        self.withdrawal_and_return()
        old = self.package('late', 10, 11)
        direct = self.package('received', 10, 12)
        other = encode_v1(replace(decode_v1(old), package_id='received'))
        self.source.close()
        receipt = accept_package(self.mirror, direct)
        record_review(self.mirror, DAY, 12, 'R', '刊次 12 现场复核')
        self.reopen_mirror()
        signed = create_signoff(self.mirror, 'after-re-review', DAY, 12)
        self.assertEqual(accept_package(self.mirror, direct), receipt)
        with self.assertRaises(WrongFrontier):
            accept_package(self.mirror, old)
        with self.assertRaises(NameConflict):
            accept_package(self.mirror, other)
        self.assertEqual(read_frontier(self.mirror, DAY), 12)
        self.assertEqual(read_current_ledger(self.mirror, DAY), signed.ledger)
        self.assertEqual(load_current_reviews(self.mirror, DAY, 12),
                         {'R': '刊次 12 现场复核', 'S': FIRST_REVIEWS['S']})
        self.assertIsNone(find_receipt(self.mirror, 'late'))
        self.assertEqual(find_receipt(self.mirror, 'received'), receipt)
        self.assertEqual(self.receipt_count(), 1)

    def test_original_retry_after_further_advance(self):
        self.baseline()
        self.review_start()
        self.withdrawal_and_return()
        self.release(13)
        old_wire = self.package('first-jump', 10, 12)
        next_wire = self.package('further', 12, 13)
        self.source.close()
        old_receipt = accept_package(self.mirror, old_wire)
        record_review(self.mirror, DAY, 12, 'R', '刊次 12 新结论')
        accept_package(self.mirror, next_wire)
        self.reopen_mirror()
        equivalent_wire = json.dumps(json.loads(old_wire), indent=2).encode()
        self.assertEqual(accept_package(self.mirror, equivalent_wire), old_receipt)
        self.assertEqual(read_frontier(self.mirror, DAY), 13)
        self.assertEqual(load_current_reviews(self.mirror, DAY, 13),
                         {'R': '刊次 12 新结论', 'S': FIRST_REVIEWS['S']})
        self.assertEqual(self.receipt_count(), 2)

    def test_dispatch_name_conflict(self):
        self.baseline()
        self.withdrawal_and_return()
        wire = self.package('fixed', 10, 12)
        self.reopen_source()
        self.assertEqual(self.package('fixed', 10, 12), wire)
        with self.assertRaises(NameConflict):
            self.package('fixed', 10, 11)
        self.assertEqual(self.package('fixed', 10, 12), wire)
