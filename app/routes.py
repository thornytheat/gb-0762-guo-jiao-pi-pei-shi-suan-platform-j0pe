from flask import Blueprint, current_app, jsonify, request

from .errors import TrialError
from .input import from_request
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.certificate.service import issue
from .modules.ledger.service import commit, rows, totals
from .pipeline import process

api = Blueprint('trial_api', __name__, url_prefix='/api')


def preview(stage):
    limits = totals(_ledger())
    return process(from_request(), stage, limits)[stage]


@api.post('/assay')
def assay():
    return preview('assay')


@api.post('/dry')
def dry():
    return preview('dry')


@api.post('/reuse')
def reuse():
    return preview('reuse')


@api.post('/formula')
def formula():
    return preview('formula')


@api.post('/blend')
def blend():
    return preview('blend')


@api.post('/stock')
def stock():
    return preview('stock')


@api.post('/batches')
def batches():
    record, fresh = preserve(current_app.config['ARCHIVE'], from_request(), totals(_ledger()))
    return {'batch_id': record['batch_id'], 'created': fresh, 'record': record}, 201 if fresh else 200


@api.get('/batches')
def list_batches():
    return {'batches': history(current_app.config['ARCHIVE'])}


@api.get('/batches/<identifier>')
def batch(identifier):
    return read(current_app.config['ARCHIVE'], identifier)


def _ledger():
    return current_app.config['LEDGER']


def _issue_fields():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise TrialError('JSON_REQUIRED', 400)
    return body


@api.post('/issues')
def issue_drum():
    body = _issue_fields()
    material = from_request(extra={'drum', 'grams', 'key'})
    drum, grams, key = body.get('drum'), body.get('grams'), body.get('key')
    record, fresh, after = commit(_ledger(), material, drum, grams, key,
                                  lambda data, limits: process(data, 'stock', limits))
    return {'issue': record, 'created': fresh, 'after': after and after['reuse']}, 201 if fresh else 200


@api.get('/issues')
def list_issues():
    return {'issues': rows(_ledger()), 'totals': totals(_ledger())}


@api.get('/certificate/<identifier>')
def certificate(identifier):
    return issue(batch(identifier))


@api.get('/export/<identifier>')
def export(identifier):
    response = jsonify(certificate(identifier))
    response.headers['Content-Disposition'] = f'attachment; filename="pectin-{identifier[:12]}.json"'
    return response
