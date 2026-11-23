from concurrent.futures import ThreadPoolExecutor

from app.input import load
from app.main import create_app


def client(tmp_path):
    return create_app(tmp_path / 'trials', tmp_path / 'issues').test_client()


def payload():
    material = load('reuse')
    return {'assays': material['assays'], 'plan': material['plan'], 'drums': material['drums']}


def test_issue_is_idempotent_per_key(tmp_path):
    api = client(tmp_path)
    body = {**payload(), 'drum': 'D-01', 'grams': 2500, 'key': 'PO-1'}
    first, replay = api.post('/api/issues', json=body), api.post('/api/issues', json=body)
    assert (first.status_code, replay.status_code, replay.json['created']) == (201, 200, False)
    assert first.json['issue'] == replay.json['issue']
    assert api.get('/api/issues').json['totals'] == {'D-01': 2500}


def test_same_key_different_amount_conflicts(tmp_path):
    api = client(tmp_path)
    api.post('/api/issues', json={**payload(), 'drum': 'D-01', 'grams': 1000, 'key': 'PO-1'})
    reply = api.post('/api/issues', json={**payload(), 'drum': 'D-01', 'grams': 2000, 'key': 'PO-1'})
    assert (reply.status_code, reply.json['code']) == (409, 'IDEMPOTENCY_CONFLICT')
    assert api.get('/api/issues').json['totals'] == {'D-01': 1000}


def test_same_key_different_material_conflicts(tmp_path):
    api = client(tmp_path)
    first = {**payload(), 'drum': 'D-01', 'grams': 1000, 'key': 'PO-1'}
    assert api.post('/api/issues', json=first).status_code == 201
    edited = {**first, 'plan': {**first['plan'], 'target_g': 2500}}
    reply = api.post('/api/issues', json=edited)
    assert (reply.status_code, reply.json['code']) == (409, 'IDEMPOTENCY_CONFLICT')
    assert api.get('/api/issues').json['totals'] == {'D-01': 1000}


def test_failed_issue_retry_does_not_double_draw(tmp_path):
    api = client(tmp_path)
    body = {**payload(), 'drum': 'D-01', 'grams': 4000, 'key': 'PO-1'}
    assert api.post('/api/issues', json=body).status_code == 201
    over = {**body, 'key': 'PO-2', 'grams': 2000}
    assert api.post('/api/issues', json=over).json['code'] == 'OVER_DRUM'
    assert api.post('/api/issues', json=over).json['code'] == 'OVER_DRUM'
    assert api.get('/api/issues').json['totals'] == {'D-01': 4000}
    last = {**body, 'key': 'PO-3', 'grams': 1000}
    assert api.post('/api/issues', json=last).status_code == 201
    assert api.get('/api/issues').json['totals'] == {'D-01': 5000}


def test_concurrent_issues_never_overdraw_same_drum(tmp_path):
    app = create_app(tmp_path / 'trials', tmp_path / 'issues')
    body = {**payload(), 'drum': 'D-01', 'grams': 3000}

    def submit(index):
        return app.test_client().post('/api/issues', json={**body, 'key': f'PO-{index}'})

    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(submit, range(6)))
    assert sorted(reply.status_code for reply in replies) == [201, 409, 409, 409, 409, 409]
    assert app.test_client().get('/api/issues').json['totals'] == {'D-01': 3000}


def test_non_reusable_and_unknown_drums_rejected(tmp_path):
    api = client(tmp_path)
    base = {**payload(), 'key': 'PO-1', 'grams': 1000}
    assert api.post('/api/issues', json={**base, 'drum': 'D-02'}).json['code'] == 'DRUM_NOT_REUSABLE'
    assert api.post('/api/issues', json={**base, 'drum': 'D-03'}).json['code'] == 'DRUM_NOT_REUSABLE'
    assert api.post('/api/issues', json={**base, 'drum': 'NOPE'}).json['code'] == 'DRUM_NOT_FOUND'
    assert api.get('/api/issues').json['issues'] == []


def test_issue_requires_positive_integer_and_key(tmp_path):
    api = client(tmp_path)
    base = {**payload(), 'drum': 'D-01', 'key': 'PO-1'}
    for grams in (0, -1, '2500', 2.5, True):
        assert api.post('/api/issues', json={**base, 'grams': grams}).json['code'] == 'BAD_ISSUE'
    assert api.post('/api/issues', json={**base, 'grams': 2500, 'key': ''}).json['code'] == 'BAD_ISSUE'
    assert api.get('/api/issues').json['totals'] == {}


def test_stock_preview_uses_ledger(tmp_path):
    api = client(tmp_path)
    api.post('/api/issues', json={**payload(), 'drum': 'D-01', 'grams': 2500, 'key': 'PO-1'})
    stock = api.post('/api/stock', json={'sample': 'reuse'}).json
    # 账本已领 2500 g 先记在 prior；本单只能再规划桶余下的 2500 g，余量由原批补。
    assert (stock['prior_g'], stock['drum_issued_g'], stock['lot_issued_g']) == (2500, 2500, 2500)
    assert stock['cumulative_issued_g'] == 7500 and stock['shortage_g'] == 0
    drum_row = next(row for row in stock['rows'] if row['lot'] == 'D-01')
    assert (drum_row['issued_g'], drum_row['end_g']) == (2500, 0)
    assert drum_row['trace'] == [{'lot': 'R-01', 'grams': 1500}, {'lot': 'R-02', 'grams': 1000}]


def test_issue_replay_after_five_units_still_reports_same_balance(tmp_path):
    api = client(tmp_path)
    body = {**payload(), 'drum': 'D-01', 'grams': 5000, 'key': 'PO-1'}
    first = api.post('/api/issues', json=body).json
    replay = api.post('/api/issues', json=body).json
    assert (first['issue'], first['after']) == (replay['issue'], replay['after'])
    assert replay['after']['drums'][0]['issuable_g'] == 0
