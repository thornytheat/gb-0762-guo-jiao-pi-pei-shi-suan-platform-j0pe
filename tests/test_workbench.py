import json

from app.input import load
from app.pipeline import process
from app.stages import STAGES


def test_station_links_and_stock_page(client):
    home = client.get('/')
    assert '配方余量轨'.encode() in home.data and b'17000 g' in home.data
    for path, name in STAGES:
        reply = client.get('/trial/' + path)
        assert reply.status_code == 200 and name.encode() in reply.data


def test_invalid_form_retains_repair_fields(client):
    response = client.post('/trial/formula', data={'sample':'custom','proposal':'{broken','assays':'draft,row','step_g':'350'})
    assert all(value in response.data for value in (b'BAD_PROPOSAL_JSON', b'{broken', b'draft,row', b'350'))


def custom_form(body, **extra):
    data = {key: str(value) for key, value in body['plan'].items()}
    data.update({'sample': 'custom', 'assays': body['assays'], 'drums': json.dumps(body['drums']),
                 'proposal': json.dumps(body['proposal'])})
    data.update(extra)
    return data


def test_custom_form_issue_posts_material_with_issue_fields(tmp_path):
    from app.main import create_app
    api = create_app(tmp_path / 'trials', tmp_path / 'issues').test_client()
    body = load('reuse')
    data = custom_form(body, drum='D-01', grams='1500', key='WEB-CUSTOM')
    reply = api.post('/trial/stock', data=data)
    assert reply.status_code == 200 and '已领用 D-01 1500 g'.encode() in reply.data
    assert api.get('/api/issues').json['totals'] == {'D-01': 1500}


def test_web_issue_failure_keeps_material_and_reports_code(tmp_path):
    from app.main import create_app
    api = create_app(tmp_path / 'trials', tmp_path / 'issues').test_client()
    data = custom_form(load('reuse'), drum='D-02', grams='1000', key='WEB-FAIL')
    reply = api.post('/trial/stock', data=data)
    assert b'DRUM_NOT_REUSABLE' in reply.data and b'WEB-FAIL' in reply.data
    assert api.get('/api/issues').json['issues'] == []


def test_reuse_page_shows_verdict_and_issuable(client):
    page = client.get('/trial/reuse?sample=reuse').data.decode()
    assert '合桶回用判定' in page and '可领 5000 g' in page
    assert 'EXPIRED_SOURCE' in page and 'REJECTED' in page
    for drum in ('D-01', 'D-02', 'D-03', 'D-04', 'D-05'):
        assert drum in page


def test_no_drums_keeps_plain_stock(client):
    result = process({**load('reuse'), 'drums': []}, 'stock')
    assert result['stock']['drummed_g'] == 0 and result['stock']['balanced'] is True
