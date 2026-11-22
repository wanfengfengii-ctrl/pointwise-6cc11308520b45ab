import json
from dataclasses import replace

from dispatch.codec import decode_v1, encode_v1
from dispatch.receipts import load_frozen_package
from intake.batches import import_batch
from intake.provenance import Provenance
from ledger_core import InvalidInput, MissingRecord
from mirror.acceptance import accept_package, bootstrap_mirror
from mirror.frontiers import read_frontier
from mirror.history import find_receipt
from mirror.materialization import read_current_ledger, read_received_ledger
from publication.issues import publish_issue
from review.lookup import read_signoff
from review.signoff import create_signoff
from tests.fixtures import DAY, FIRST_REVIEWS, LedgerTestCase, observations, row_ids


class HandoffTests(LedgerTestCase):
    def test_adjacent(self):
        start = self.baseline(('R', 7), ('S', 11), ('M', None))
        self.review_start()
        target = self.release(11, R=False, M=False)
        body = self.package('next', 10, 11)
        self.source.close()
        receipt = accept_package(self.mirror, body)
        signed = create_signoff(self.mirror, 'next-signoff', DAY, 11)
        self.assertEqual((receipt.package_id, receipt.start, receipt.target), ('next', 10, 11))
        self.assertEqual(signed.ledger, target)
        self.assertEqual(row_ids(signed.ledger), ('S',))
        self.assertEqual(tuple(row.source for row in signed.ledger.rows),
                         (Provenance('Q1', 'Q1 field sheet', 102),))
        self.assertEqual((signed.ledger.totals.liters, signed.ledger.totals.missing), (11, 0))
        self.assertEqual(signed.conclusions, (FIRST_REVIEWS['S'],))
        self.assertEqual(read_current_ledger(self.mirror, DAY), target)
        self.assertEqual(read_received_ledger(self.mirror, DAY, 10), start)

    def test_interval_guard(self):
        self.baseline()
        self.release(11)
        import_batch(self.source, 'different day', 'different batch', observations(('R', 5)))
        publish_issue(self.source, 'different day', 12)
        for package_id, start, target, error in (
            ('reverse', 11, 10, InvalidInput), ('equal', 11, 11, InvalidInput),
            ('unknown-start', 9, 11, MissingRecord), ('wrong-day-endpoint', 10, 12, MissingRecord),
        ):
            with self.subTest(package_id=package_id):
                with self.assertRaises(error):
                    self.package(package_id, start, target)
                self.assertIsNone(load_frozen_package(self.source, package_id))
        self.assertEqual(decode_v1(self.package('unknown-start', 10, 11)).target, 11)

    def test_skipped_withdrawal(self):
        start = self.baseline()
        self.review_start()
        original = create_signoff(self.mirror, 'base-signed', DAY, 10)
        middle, target = self.withdrawal_and_return()
        self.assertEqual(row_ids(middle), ('S',))
        self.assertEqual(start.rows, target.rows)
        body = self.package('combined', 10, 12)
        self.source.close()
        receipt = accept_package(self.mirror, body)
        signed = create_signoff(self.mirror, 'combined-signed', DAY, 12)
        self.assertEqual(signed.ledger.rows, start.rows)
        self.assertEqual(tuple(row.liters for row in signed.ledger.rows), (7, 11))
        self.assertEqual((signed.ledger.totals.liters, signed.ledger.totals.missing), (18, 0))
        self.assertIsNone(signed.conclusions[0], 'R_REVIEW_WRONGLY_RETAINED')
        self.assertEqual(signed.conclusions[1], FIRST_REVIEWS['S'])
        self.assertEqual(signed.states, ('pending', 'reviewed'))
        self.assertEqual(read_frontier(self.mirror, DAY), 12)
        self.assertEqual(find_receipt(self.mirror, 'combined'), receipt)
        self.assertEqual(self.receipt_count(), 1)
        self.assertEqual(read_signoff(self.mirror, 'base-signed'), original)
        self.assertEqual(original.states, ('reviewed', 'reviewed'))

    def test_sequential_equivalence(self):
        start = self.baseline()
        second = self.open_mirror('sequential.sqlite')
        bootstrap_mirror(second, start)
        self.review_start()
        self.review_start(second)
        self.withdrawal_and_return()
        first_wire = self.package('middle', 10, 11)
        second_wire = self.package('last', 11, 12)
        combined_wire = self.package('direct', 10, 12)
        self.source.close()
        accept_package(second, first_wire)
        accept_package(second, second_wire)
        accept_package(self.mirror, combined_wire)
        direct = create_signoff(self.mirror, 'direct-sign', DAY, 12)
        sequential = create_signoff(second, 'seq-sign', DAY, 12)
        self.assertEqual(direct.ledger, sequential.ledger)
        self.assertEqual(direct.conclusions, sequential.conclusions)
        self.assertEqual(direct.conclusions, (None, FIRST_REVIEWS['S']))
        self.assertEqual((direct.ledger.totals.liters, direct.ledger.totals.missing), (18, 0))
        self.assertEqual(read_frontier(second, DAY), 12)
        self.assertIsNotNone(find_receipt(second, 'middle'))
        self.assertIsNotNone(find_receipt(second, 'last'))
        self.assertEqual(self.receipt_count(), 1)
        self.assertIsNone(find_receipt(self.mirror, 'middle'))
        self.assertIsNone(find_receipt(self.mirror, 'last'))
        with self.assertRaises(MissingRecord):
            read_received_ledger(self.mirror, DAY, 11)

    def test_draft_does_not_break_review(self):
        base = self.baseline()
        self.review_start()
        self.stage(R=False)
        self.stage(R=True)
        self.assertEqual(self.release(11).rows, base.rows)
        self.assertEqual(self.release(12).rows, base.rows)
        body = self.package('draft-control', 10, 12)
        self.source.close()
        accept_package(self.mirror, body)
        signed = create_signoff(self.mirror, 'draft-control-sign', DAY, 12)
        self.assertEqual(signed.ledger.rows, base.rows)
        self.assertEqual(signed.conclusions, (FIRST_REVIEWS['R'], FIRST_REVIEWS['S']))
        self.assertEqual((signed.ledger.totals.liters, signed.ledger.totals.missing), (18, 0))

    def test_unpublished_at_dispatch(self):
        base = self.baseline()
        self.review_start()
        self.release(11)
        self.stage(R=False)
        body = self.package('draft-pending', 10, 11)
        self.source.close()
        accept_package(self.mirror, body)
        signed = create_signoff(self.mirror, 'draft-pending-sign', DAY, 11)
        self.assertEqual(signed.ledger.rows, base.rows)
        self.assertEqual(row_ids(signed.ledger), ('R', 'S'))
        self.assertEqual(signed.conclusions, (FIRST_REVIEWS['R'], FIRST_REVIEWS['S']))
        self.assertEqual((signed.ledger.totals.liters, signed.ledger.totals.missing), (18, 0))

    def test_nonconsecutive_issues_and_day_isolation(self):
        self.baseline()
        self.review_start()
        alternate = '独立日表'
        import_batch(self.source, alternate, 'alternate', observations(('R', 1)))
        publish_issue(self.source, alternate, 15)
        self.release(30, R=False)
        self.release(110, R=True)
        body = self.package('nonconsecutive', 10, 110)
        self.source.close()
        accept_package(self.mirror, body)
        result = create_signoff(self.mirror, 'nonconsecutive-sign', DAY, 110)
        self.assertEqual(result.conclusions, (None, FIRST_REVIEWS['S']))
        self.assertEqual(row_ids(result.ledger), ('R', 'S'))
        self.assertIsNone(read_frontier(self.mirror, alternate))

    def test_invalid_payload_is_atomic(self):
        base = self.baseline()
        self.review_start()
        self.withdrawal_and_return()
        wire = self.package('checked', 10, 12)
        self.source.close()
        bad_total = json.loads(wire)
        bad_total['ledger']['totals']['liters'] = '17'
        missing_evidence = json.loads(wire)
        del missing_evidence['evidence']
        duplicate_key = json.loads(wire)
        duplicate_key['evidence']['continuous'] *= 2
        bad_version = json.loads(wire)
        bad_version['version'] = True
        package = decode_v1(wire)
        wrong_base = encode_v1(replace(package, evidence=replace(package.evidence, base_sha256='0' * 64)))
        duplicate_field = b'{"version":1,' + wire[1:]
        invalid = [json.dumps(value).encode() for value in
                   (bad_total, missing_evidence, duplicate_key, bad_version)]
        for body in [*invalid, wrong_base, duplicate_field]:
            with self.assertRaises(InvalidInput):
                accept_package(self.mirror, body)
            self.assertIsNone(find_receipt(self.mirror, 'checked'))
            self.assertEqual(read_current_ledger(self.mirror, DAY), base)
        current = create_signoff(self.mirror, 'after-refusal', DAY, 10)
        self.assertEqual(current.states, ('reviewed', 'reviewed'))
        self.assertEqual(accept_package(self.mirror, wire).target, 12)
