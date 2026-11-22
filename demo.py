import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from archive_medium import create_medium, open_medium
from dispatch.packages import dispatch_package
from intake.batches import import_batch
from mirror.acceptance import accept_package, bootstrap_mirror
from mirror.frontiers import read_frontier
from mirror.history import find_receipt
from mirror.storage import open_mirror
from publication.drafts import QualityDecision, stage_decisions
from publication.issues import publish_issue
from review.decisions import record_review
from review.lookup import read_archive, read_signoff
from review.signoff import archive, create_signoff
from source_store import open_source


def _require_equal(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


def _daily_summary(ledger):
    return {'issue': ledger.issue, 'row_ids': [row.key.row_id for row in ledger.rows],
            'liters': ledger.totals.liters, 'missing': ledger.totals.missing}


def main():
    sample = Path(__file__).resolve().parent / 'samples' / 'observations.json'
    payload = json.loads(sample.read_text(encoding='utf-8'))
    day = payload['day']
    with TemporaryDirectory() as directory:
        base = Path(directory)
        with closing(open_mirror(base / 'night.sqlite')) as mirror:
            with closing(open_source(base / 'day.sqlite')) as source:
                rows = payload['rows']
                import_batch(source, day, payload['batch_id'], rows)
                stage_decisions(source, day, [QualityDecision(row['row_id'], True) for row in rows])
                daily = publish_issue(source, day, 9)
                _require_equal(_daily_summary(daily), {
                    'issue': 9, 'row_ids': ['R', 'S', 'Z', 'M'], 'liters': 18, 'missing': 1,
                })
                stage_decisions(source, day, [QualityDecision('Z', False), QualityDecision('M', False)])
                start = publish_issue(source, day, 10)
                bootstrap_mirror(mirror, start)
                record_review(mirror, day, 10, 'R', '已核对 R 原据')
                record_review(mirror, day, 10, 'S', '已核对 S 原据')
                original = create_signoff(mirror, '早班底账', day, 10)
                stage_decisions(source, day, [QualityDecision('R', False)])
                middle = publish_issue(source, day, 11)
                stage_decisions(source, day, [QualityDecision('R', True)])
                target = publish_issue(source, day, 12)
                wire = dispatch_package(source, '夜班合并件', day, 10, 12)

            receipt = accept_package(mirror, wire)
            signed = create_signoff(mirror, '夜班目标账', day, 12)
            actual = _daily_summary(signed.ledger)
            actual['states'] = dict(zip(actual['row_ids'], signed.states, strict=True))
            actual['readings'] = [row.liters for row in signed.ledger.rows]
            actual['source_lines'] = [row.source.line for row in signed.ledger.rows]
            expected = {
                'issue': 12, 'row_ids': ['R', 'S'], 'liters': 18, 'missing': 0,
                'states': {'R': 'pending', 'S': 'reviewed'}, 'readings': [7, 11],
                'source_lines': [21, 22],
            }
            _require_equal(actual, expected)
            _require_equal(signed.conclusions, (None, '已核对 S 原据'))
            _require_equal(signed.ledger, target)
            replay = accept_package(mirror, wire)
            historical = read_signoff(mirror, '早班底账')
            downstream_actual = {
                'frontier': read_frontier(mirror, day),
                'receipt_interval': [replay.start, replay.target],
                'same_receipt': replay == receipt == find_receipt(mirror, '夜班合并件'),
                'old_issue': historical.ledger.issue,
                'old_states': list(historical.states),
                'old_unchanged': historical == original,
            }
            downstream_expected = {
                'frontier': 12, 'receipt_interval': [10, 12], 'same_receipt': True,
                'old_issue': 10, 'old_states': ['reviewed', 'reviewed'], 'old_unchanged': True,
            }
            _require_equal(downstream_actual, downstream_expected)
            print('POINTWISE_SCENARIO ' + json.dumps({
                'case_id': 'skipped',
                'input': {'day': day, 'batch': payload, 'start': _daily_summary(start),
                          'withdrawal': _daily_summary(middle), 'target': _daily_summary(target)},
                'expected': expected, 'actual': actual,
                'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
                'code_paths': ['publication/issues.py', 'dispatch/evidence.py', 'mirror/acceptance.py',
                               'review/eligibility.py', 'review/signoff.py', 'review/lookup.py'],
                'oracle': '手算 7 + 11 = 18。R 在正式刊次 11 缺席，S 在 10、11、12 一直在表。'
                          '目标复核只延续 S。编号 10 的签读保留两条原结论。',
            }, ensure_ascii=False, sort_keys=True))

        # 冷盘归档演示：全四行刊次 9 装入另一座夜班库，冻结签读 F 后改录现场结论，
        # 首写收令失答、重开待定、设备封成首槽，最后卸盘只凭介质冷读回原签读。
        cold_night_path = base / 'cold-night.sqlite'
        cold_medium_path = base / 'cold-medium.sqlite'
        cold_night = open_mirror(cold_night_path)
        bootstrap_mirror(cold_night, daily)
        record_review(cold_night, day, 9, 'R', '已核对')
        frozen = create_signoff(cold_night, 'F', day, 9)
        record_review(cold_night, day, 9, 'R', '改录：R 原据待补')
        medium = create_medium(cold_medium_path, '冷盘-QX', 2)
        medium.hold_next_write()
        first_reply = archive(cold_night, '夜班归档-F', 'F', medium)
        medium.close()
        cold_night.close()
        _require_equal(first_reply, ('pending', None))
        cold_night = open_mirror(cold_night_path)
        medium = open_medium(cold_medium_path)
        _require_equal([medium.status(slot) for slot in range(2)], ['writing', 'empty'])
        _require_equal(archive(cold_night, '夜班归档-F', 'F', medium), ('pending', None))
        _require_equal(medium.status(1), 'empty')
        device = open_medium(cold_medium_path)
        device.finish(0, 'sealed')
        device.close()
        final_reply = archive(cold_night, '夜班归档-F', 'F', medium)
        _require_equal(final_reply, ('sealed', ('夜班归档-F', 'F', '冷盘-QX', 0)))
        _require_equal(archive(cold_night, '夜班归档-F', 'F', medium), final_reply)
        _require_equal([medium.status(slot) for slot in range(2)], ['sealed', 'empty'])
        medium.close()
        cold_night.close()
        reader = open_medium(cold_medium_path, read_only=True)
        back = read_archive(reader, '夜班归档-F')
        reader.close()
        _require_equal(back, frozen)
        archive_actual = {
            'slot': final_reply[1][3],
            'medium_slots': ['sealed', 'empty'],
            'row_ids': [row.key.row_id for row in back.ledger.rows],
            'liters': [row.liters for row in back.ledger.rows],
            'provenance': [{'station': row.source.station, 'document': row.source.document,
                            'line': row.source.line} for row in back.ledger.rows],
            'totals': {'liters': back.ledger.totals.liters, 'missing': back.ledger.totals.missing},
            'conclusions': list(back.conclusions),
            'states': list(back.states),
        }
        archive_expected = {
            'slot': 0,
            'medium_slots': ['sealed', 'empty'],
            'row_ids': ['R', 'S', 'Z', 'M'],
            'liters': [7, 11, 0, None],
            'provenance': [{'station': 'QX-01', 'document': '晨班现场记录', 'line': line}
                           for line in (21, 22, 23, 24)],
            'totals': {'liters': 18, 'missing': 1},
            'conclusions': ['已核对', None, None, None],
            'states': ['reviewed', 'pending', 'pending', 'pending'],
        }
        _require_equal(archive_actual, archive_expected)
        print('POINTWISE_ARCHIVE ' + json.dumps({
            'case_id': 'cold-archive-lost-reply',
            'archive_id': '夜班归档-F',
            'signoff_id': back.signoff_id,
            'issue': back.ledger.issue,
            'receipt': list(final_reply[1]),
            'expected': archive_expected,
            'actual': archive_actual,
            'matches_frozen_signoff': back == frozen,
            'code_paths': ['review/signoff.py', 'review/cold.py', 'review/lookup.py',
                           'archive_medium.py'],
            'oracle': '首写收令失答后首槽在写，同号重投待定且另一槽保持空闲；设备封成首槽后'
                      '同号领回首槽收执，全盘只此一件。卸盘冷读凭介质核出原签读：原序 R、S、Z、M，'
                      '读值 7、11、0、缺测，出处行 21-24，合计 18 L、缺测一行，'
                      'R 的冻结结论仍为「已核对」。',
        }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
