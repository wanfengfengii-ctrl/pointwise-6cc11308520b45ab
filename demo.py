import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from dispatch.packages import dispatch_package
from intake.batches import import_batch
from mirror.acceptance import accept_package, bootstrap_mirror
from mirror.frontiers import read_frontier
from mirror.history import find_receipt
from mirror.storage import open_mirror
from publication.drafts import QualityDecision, stage_decisions
from publication.issues import publish_issue
from review.decisions import record_review
from review.lookup import read_signoff
from review.signoff import create_signoff
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


if __name__ == '__main__':
    main()
