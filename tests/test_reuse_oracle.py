from app.input import load
from app.pipeline import process
def test_drum_and_lot_capacity_never_double_counts(reuse):
    """原批转入桶的料只在桶上出现一次；可分配量 = 原批余量 + 桶余量。"""
    result = process(reuse, 'stock')
    lots = {row['lot']: row for row in result['reuse']['lots']}
    drums = {row['drum']: row for row in result['reuse']['drums']}
    for drum in drums.values():
        if drum['status'] == 'REUSABLE':
            for source in drum['sources']:
                lot = lots[source['lot']]
                assert lot['drummed_g'] >= source['grams']
    total = sum(row['available_g'] for row in result['reuse']['lots'] if row['status'] == 'ELIGIBLE')
    total += sum(row['issuable_g'] for row in result['reuse']['drums'])
    assert total == 3000 + 2000 + 2000 + 5000  # R-02 + R-01 + R-04 + D-01


def test_repeated_issue_keeps_warehouse_identity(tmp_path):
    from app.main import create_app
    app = create_app(tmp_path / 'trials', tmp_path / 'issues')
    api = app.test_client()
    material = load('reuse')
    body = {'assays': material['assays'], 'plan': material['plan'], 'drums': material['drums'], 'drum': 'D-01'}
    seen = []
    for index, grams in enumerate((1000, 1500, 2500)):
        reply = api.post('/api/issues', json={**body, 'grams': grams, 'key': f'P-{index}'})
        assert reply.status_code == 201
        after = reply.json['after']
        assert after['balanced'] is True
        seen.append(after['issuable_g'])
    assert seen == [4000, 2500, 0]
    stock = api.post('/api/stock', json={'sample': 'reuse'}).json
    drum = next(row for row in stock['rows'] if row['lot'] == 'D-01')
    assert (drum['prior_g'], drum['end_g']) == (5000, 0)
    assert stock['cumulative_issued_g'] == stock['prior_g']


def test_any_drum_issue_allocates_only_from_that_drum(tmp_path):
    from app.main import create_app
    api = create_app(tmp_path / 'trials', tmp_path / 'issues').test_client()
    material = load('reuse')
    reply = api.post('/api/issues', json={**material, 'drum': 'D-01', 'grams': 5000, 'key': 'P-1'})
    after = reply.json['after']
    assert after['issuable_g'] == 0
    assert after['drummed_g'] == 13000  # 5 个桶里 2 个不可核对，其余 13,000 g 各从原批转出一次


def test_trace_sums_to_issue():
    from app.modules.reuse.service import trace_issue
    sources = [{'lot': 'A', 'grams': 1}, {'lot': 'B', 'grams': 1}, {'lot': 'C', 'grams': 1}]
    for grams in range(0, 40):
        parts = trace_issue({'sources': sources}, grams)
        assert sum(part['grams'] for part in parts) == grams
        assert all(part['grams'] >= 0 for part in parts)
