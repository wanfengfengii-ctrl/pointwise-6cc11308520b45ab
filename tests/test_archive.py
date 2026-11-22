import json
import subprocess
import sys
from pathlib import Path

from archive_medium import create_medium, open_medium
from intake.batches import import_batch
from ledger_core import InvalidInput, MissingRecord, NameConflict
from mirror.acceptance import bootstrap_mirror
from publication.drafts import QualityDecision, stage_decisions
from publication.issues import publish_issue
from review.decisions import record_review
from review.lookup import read_archive
from review.signoff import archive, create_signoff
from tests.fixtures import LedgerTestCase

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = json.loads((ROOT / 'samples' / 'observations.json').read_text(encoding='utf-8'))
DAY = SAMPLE['day']
ARCHIVE = '夜班归档-F'
SIGNOFF = 'F'
REVIEW = '已核对'
MEDIUM = '冷盘-QX'


class ArchiveTests(LedgerTestCase):
    def prepare_signoff(self, conclusion=REVIEW):
        """Publish the four sample rows at issue 9, review R and freeze the signoff."""
        rows = SAMPLE['rows']
        import_batch(self.source, DAY, SAMPLE['batch_id'], rows)
        stage_decisions(self.source, DAY, [QualityDecision(row['row_id'], True) for row in rows])
        issue = publish_issue(self.source, DAY, 9)
        bootstrap_mirror(self.mirror, issue)
        record_review(self.mirror, DAY, 9, 'R', conclusion)
        return create_signoff(self.mirror, SIGNOFF, DAY, 9)

    def make_medium(self, filename='medium.sqlite', medium_id=MEDIUM, slots=2):
        medium = create_medium(self.directory / filename, medium_id, slots)
        self.addCleanup(medium.close)
        return medium

    def reopen_medium(self, filename='medium.sqlite', read_only=False):
        medium = open_medium(self.directory / filename, read_only=read_only)
        self.addCleanup(medium.close)
        return medium

    def assert_sample_signoff(self, signoff, frozen):
        self.assertEqual(signoff, frozen)
        self.assertEqual(signoff.signoff_id, SIGNOFF)
        self.assertEqual((signoff.ledger.day, signoff.ledger.issue), (DAY, 9))
        rows = signoff.ledger.rows
        self.assertEqual(tuple(row.key.row_id for row in rows), ('R', 'S', 'Z', 'M'))
        self.assertEqual([row.liters for row in rows], [7, 11, 0, None])
        self.assertEqual([row.source.line for row in rows], [21, 22, 23, 24])
        self.assertEqual({row.source.station for row in rows}, {'QX-01'})
        self.assertEqual({row.source.document for row in rows}, {'晨班现场记录'})
        self.assertEqual((signoff.ledger.totals.liters, signoff.ledger.totals.missing), (18, 1))
        self.assertEqual(signoff.conclusions, (REVIEW, None, None, None))
        self.assertEqual(signoff.states, ('reviewed', 'pending', 'pending', 'pending'))

    def test_lost_reply_then_device_seals(self):
        frozen = self.prepare_signoff()
        record_review(self.mirror, DAY, 9, 'R', '改录：R 原据待补')
        self.source.close()
        self.make_medium().close()
        writer = """
import sys
from archive_medium import open_medium
from mirror.storage import open_mirror
from review.signoff import archive
mirror = open_mirror(sys.argv[1])
device = open_medium(sys.argv[2])
device.hold_next_write()
result = archive(mirror, sys.argv[3], sys.argv[4], device)
assert result == ('pending', None), result
device.close()
mirror.close()
"""
        # The first write is accepted but its reply is lost, then the archiving
        # process exits without learning the outcome.
        subprocess.run([sys.executable, '-B', '-c', writer,
                        str(self.mirror_path), str(self.directory / 'medium.sqlite'),
                        ARCHIVE, SIGNOFF], check=True, cwd=ROOT)
        self.reopen_mirror()
        medium = self.reopen_medium()
        self.assertEqual([medium.status(slot) for slot in range(2)], ['writing', 'empty'])
        # The original command may still seal: same-id retry stays pending and
        # the other slot stays empty.
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('pending', None))
        self.assertEqual([medium.status(slot) for slot in range(2)], ['writing', 'empty'])
        device = self.reopen_medium()
        device.finish(0, 'sealed')
        device.close()
        receipt = (ARCHIVE, SIGNOFF, MEDIUM, 0)
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('sealed', receipt))
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('sealed', receipt))
        self.assertEqual([medium.status(slot) for slot in range(2)], ['sealed', 'empty'])
        medium.close()
        self.mirror.close()
        # Source store and night ledger are closed: cold read uses the medium alone.
        reader = self.reopen_medium(read_only=True)
        self.assert_sample_signoff(read_archive(reader, ARCHIVE), frozen)
        reader.close()

    def test_burned_then_rewrite_to_empty_slot(self):
        frozen = self.prepare_signoff()
        self.source.close()
        medium = self.make_medium()
        medium.hold_next_write()
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('pending', None))
        self.reopen_mirror()
        medium.close()
        medium = self.reopen_medium()
        self.assertEqual(medium.status(0), 'writing')
        # Still writing: no other slot is consumed yet.
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('pending', None))
        self.assertEqual(medium.status(1), 'empty')
        device = self.reopen_medium()
        device.finish(0, 'burned')
        device.close()
        # Only after the burn is confirmed may another empty slot be written.
        receipt = (ARCHIVE, SIGNOFF, MEDIUM, 1)
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('sealed', receipt))
        self.assertEqual([medium.status(slot) for slot in range(2)], ['burned', 'sealed'])
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('sealed', receipt))
        medium.close()
        self.mirror.close()
        reader = self.reopen_medium(read_only=True)
        self.assert_sample_signoff(read_archive(reader, ARCHIVE), frozen)
        reader.close()

    def test_burned_only_slot_reports_full(self):
        self.prepare_signoff()
        self.source.close()
        medium = self.make_medium(filename='single.sqlite', medium_id='冷盘-单槽', slots=1)
        medium.hold_next_write()
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('pending', None))
        medium.finish(0, 'burned')
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('full', None))
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, medium), ('full', None))
        self.assertEqual(medium.status(0), 'burned')

    def test_rebinding_and_unknown_signoff(self):
        self.prepare_signoff()
        create_signoff(self.mirror, 'G', DAY, 9)
        self.source.close()
        first = self.make_medium(filename='first.sqlite', medium_id='冷盘-甲')
        second = self.make_medium(filename='second.sqlite', medium_id='冷盘-乙')
        self.assertEqual(archive(self.mirror, ARCHIVE, SIGNOFF, first),
                         ('sealed', (ARCHIVE, SIGNOFF, '冷盘-甲', 0)))
        # An accepted archive id refuses a different signoff or medium; no command is sent.
        with self.assertRaises(NameConflict):
            archive(self.mirror, ARCHIVE, 'G', first)
        with self.assertRaises(NameConflict):
            archive(self.mirror, ARCHIVE, SIGNOFF, second)
        self.assertEqual([first.status(slot) for slot in range(2)], ['sealed', 'empty'])
        self.assertEqual([second.status(slot) for slot in range(2)], ['empty', 'empty'])
        # Unknown signoffs are missing and do not occupy the archive id.
        with self.assertRaises(MissingRecord):
            archive(self.mirror, '另一归档', '没有这条签读', first)
        self.assertEqual(archive(self.mirror, '另一归档', SIGNOFF, first),
                         ('sealed', ('另一归档', SIGNOFF, '冷盘-甲', 1)))
        self.assertEqual([first.status(slot) for slot in range(2)], ['sealed', 'sealed'])

    def test_second_archive_uses_next_empty_slot(self):
        self.prepare_signoff()
        self.source.close()
        medium = self.make_medium()
        medium.hold_next_write()
        self.assertEqual(archive(self.mirror, '甲档', SIGNOFF, medium), ('pending', None))
        self.assertEqual(archive(self.mirror, '乙档', SIGNOFF, medium),
                         ('sealed', ('乙档', SIGNOFF, MEDIUM, 1)))
        medium.finish(0, 'sealed')
        self.assertEqual(archive(self.mirror, '甲档', SIGNOFF, medium),
                         ('sealed', ('甲档', SIGNOFF, MEDIUM, 0)))
        self.assertEqual([medium.status(slot) for slot in range(2)], ['sealed', 'sealed'])
        medium.close()
        self.mirror.close()
        reader = self.reopen_medium(read_only=True)
        self.assertEqual(read_archive(reader, '甲档').signoff_id, SIGNOFF)
        self.assertEqual(read_archive(reader, '乙档').signoff_id, SIGNOFF)
        reader.close()

    def test_cold_read_requires_intact_sealed_item(self):
        self.prepare_signoff()
        self.source.close()
        # A slot still writing is not checkable.
        writing = self.make_medium(filename='writing.sqlite', medium_id='盘-写')
        writing.hold_next_write()
        self.assertEqual(archive(self.mirror, '档-写', SIGNOFF, writing), ('pending', None))
        with self.assertRaises(MissingRecord):
            read_archive(writing, '档-写')
        # A burned slot is not checkable.
        burned = self.make_medium(filename='burned.sqlite', medium_id='盘-烧')
        burned.hold_next_write()
        archive(self.mirror, '档-烧', SIGNOFF, burned)
        burned.finish(0, 'burned')
        with self.assertRaises(MissingRecord):
            read_archive(burned, '档-烧')
        # A sealed item of another archive id is not checkable under this id.
        other = self.make_medium(filename='other.sqlite', medium_id='盘-他')
        archive(self.mirror, '档-他', SIGNOFF, other)
        with self.assertRaises(MissingRecord):
            read_archive(other, '档-无')
        # A damaged sealed item is recognizable but fails its integrity check.
        damaged = self.make_medium(filename='damaged.sqlite', medium_id='盘-坏')
        archive(self.mirror, '档-坏', SIGNOFF, damaged)
        damaged.damage(0)
        with self.assertRaises(InvalidInput):
            read_archive(damaged, '档-坏')
        # Two sealed items claiming one archive id conflict.
        duplicate = self.make_medium(filename='duplicate.sqlite', medium_id='盘-重')
        archive(self.mirror, '档-重', SIGNOFF, duplicate)
        duplicate.write(1, duplicate.read_slot(0))
        with self.assertRaises(InvalidInput):
            read_archive(duplicate, '档-重')
        # Foreign bytes and an empty medium hold no checkable item.
        foreign = self.make_medium(filename='foreign.sqlite', medium_id='盘-异')
        foreign.write(0, b'x' * 100)
        with self.assertRaises(MissingRecord):
            read_archive(foreign, '档-异')
        empty = self.make_medium(filename='empty.sqlite', medium_id='盘-空')
        with self.assertRaises(MissingRecord):
            read_archive(empty, '档-空')
