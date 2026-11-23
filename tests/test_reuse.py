import pytest

from app.errors import TrialError
from app.modules.reuse.model import parse_drums
from app.pipeline import process


def run(material, stage='reuse'):
    return process(material, stage)[stage]


def drum(drum_id, sources, verdict='PASS', moisture='4.5', sag='153', created='2026-11-15'):
    return {'drum': drum_id, 'created': created,
            'sources': [{'lot': lot, 'grams': grams} for lot, grams in sources],
            'recheck': {'moisture_pct': moisture, 'gel_sag': sag, 'verdict': verdict}}


def test_rechecked_drum_still_blocked_by_expired_source(reuse):
    result = run(reuse)
    rows = {row['drum']: row for row in result['drums']}
    expired = rows['D-02']
    assert (expired['verdict'], expired['status'], expired['issuable_g']) == ('PASS', 'EXPIRED_SOURCE', 0)
    assert expired['blockers'] == ['R-03'] and expired['blocked_g'] == 5000
    assert rows['D-01']['status'] == 'REUSABLE' and rows['D-01']['issuable_g'] == 5000
    assert result['counts'] == {'REUSABLE': 1, 'REJECTED': 1, 'EXPIRED_SOURCE': 1, 'INVALID': 2}


def test_drum_expiry_is_earliest_source_date(reuse):
    row = next(row for row in run(reuse)['drums'] if row['drum'] == 'D-01')
    assert row['effective_expires'] == '2026-12-10'


def test_rejected_recheck_blocks_whole_drum(reuse):
    row = next(row for row in run(reuse)['drums'] if row['drum'] == 'D-03')
    assert (row['verdict'], row['status'], row['issuable_g']) == ('FAIL', 'REJECTED', 0)


def test_unverifiable_sources_are_invalid_and_keep_lots(reuse):
    rows = {row['drum']: row for row in run(reuse)['drums']}
    assert rows['D-05']['issues'] == ['UNKNOWN_SOURCE']
    assert rows['D-04']['issues'] == ['OVER_SOURCE']
    lots = {lot['lot']: lot for lot in run(reuse)['lots']}
    assert (lots['R-05']['stock_g'], lots['R-05']['drummed_g']) == (0, 3000)


def test_source_weight_counts_once_across_drums(reuse):
    result = run(reuse)
    assert result['drum_weight_g'] == 15000 and result['drummed_g'] == 13000
    assert result['balanced'] is True
    lots = {lot['lot']: lot for lot in result['lots']}
    assert (lots['R-02']['stock_original_g'], lots['R-02']['drummed_g'], lots['R-02']['stock_g']) == (5000, 2000, 3000)


def test_reusable_dry_and_sag_follow_whole_drum_recheck(reuse):
    result = run(reuse)
    assert result['drum_dry_g'] == '4775.0000'
    assert result['eligible_dry_g'] == '11515.0000'


def test_reusable_drum_enters_formula_and_blend(reuse):
    formula = process(reuse, 'formula')['formula']
    assert (formula['mass_g'], formula['dry_g'], formula['gel_sag'], formula['can_make']) == (5000, '4775.0000', '153.000', True)
    blend = process(reuse, 'blend')['blend']
    assert (blend['status'], blend['allocation']) == ('FEASIBLE', {'D-01': 5000})


def test_proposal_on_expired_source_drum_rejected(reuse):
    expired = {**reuse, 'proposal': {'D-02': 5000}}
    finding = process(expired, 'formula')['formula']['findings'][0]
    assert finding['codes'] == ['EXPIRED_SOURCE', 'OVER_STOCK', 'BLOCKED_R-03']


def test_drum_issue_keeps_original_lot_dates(reuse):
    result = run(reuse, 'stock')
    drum_row = next(row for row in result['rows'] if row['lot'] == 'D-01')
    assert drum_row['expires'] == '2026-12-10'
    lot_row = next(row for row in result['rows'] if row['lot'] == 'R-02')
    assert lot_row['expires'] == '2026-12-10'


def test_stock_conserves_after_drum_issue(reuse):
    result = run(reuse, 'stock')
    assert result['issued_g'] == result['drum_issued_g'] == 5000 and result['lot_issued_g'] == 0
    assert (result['begin_g'], result['drummed_g'], result['end_g'], result['shortage_g']) == (20000, 13000, 15000, 0)
    assert result['balanced'] is True


def test_issue_trace_reaches_source_lots(reuse):
    row = next(row for row in run(reuse, 'stock')['rows'] if row['lot'] == 'D-01')
    assert row['trace'] == [{'lot': 'R-01', 'grams': 3000}, {'lot': 'R-02', 'grams': 2000}]


def test_trace_uses_largest_remainder(reuse):
    from app.modules.reuse.service import trace_issue
    rows = {row['drum']: row for row in run(reuse)['drums']}
    assert trace_issue(rows['D-01'], 2500) == [{'lot': 'R-01', 'grams': 1500}, {'lot': 'R-02', 'grams': 1000}]
    assert trace_issue(rows['D-01'], 3) == [{'lot': 'R-01', 'grams': 2}, {'lot': 'R-02', 'grams': 1}]


def test_dirty_sample_without_drums_is_unchanged(dirty):
    result = run(dirty)
    assert result['drum_count'] == 0 and result['issuable_g'] == 0


@pytest.mark.parametrize('raw,code', [
    ({'drum': 'D'}, 'BAD_DRUM'),
    ([{'drum': 'D', 'sources': [], 'recheck': {'moisture_pct': 1, 'gel_sag': 1, 'verdict': 'PASS'}}], 'BAD_DRUM'),
    ([drum('D', [('R-01', 0)])], 'BAD_DRUM'),
    ([drum('D', [('R-01', 1)], verdict='OTHER')], 'BAD_DRUM'),
    ([drum('D', [('R-01', 1)], moisture='4.555')], 'BAD_DRUM'),
    ([drum('D', [('R-01', 1)]), drum('D', [('R-02', 1)])], 'DUPLICATE_DRUM'),
    ('drum', 'BAD_DRUMS'),
])
def test_drum_contract(raw, code):
    with pytest.raises(TrialError, match=code):
        parse_drums(raw)


def test_drum_numbering_formats_accepted(reuse):
    parsed = parse_drums([drum('D', [('R-01', '1,000')], verdict='合格', moisture='４.５', sag='153.001')])
    assert (parsed[0]['weight_g'], parsed[0]['recheck']['verdict']) == (1000, 'PASS')
    assert parsed[0]['recheck']['moisture_bp'] == 450 and parsed[0]['recheck']['gel_msag'] == 153001
