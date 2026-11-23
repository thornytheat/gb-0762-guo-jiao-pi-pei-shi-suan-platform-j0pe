import json

from flask import Blueprint, abort, current_app, render_template, request

from .config import REVISION
from .errors import TrialError
from .input import load
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.certificate.service import issue
from .modules.ledger.service import commit, rows as ledger_rows, totals as ledger_totals
from .pipeline import process
from .stages import ISSUE_FIELDS, LABELS, PLAN_FIELDS, STAGES

station = Blueprint('station', __name__)


def materials(mode):
    if mode != 'custom':
        return load(mode)
    try:
        proposal = json.loads(request.form.get('proposal', '{}'))
        drums = json.loads(request.form.get('drums') or '[]')
    except ValueError:
        raise TrialError('BAD_PROPOSAL_JSON') from None
    material = {'assays': request.form.get('assays', ''),
                'plan': {key: request.form.get(key, '') for key in PLAN_FIELDS}, 'proposal': proposal}
    if drums:
        material['drums'] = drums
    return material


def issue_feedback(mode, material):
    """POST 提交领用：成功/失败都回显在试算页，页面再按账本重算可领量。"""
    form = request.form
    reply = {'drum': form.get('drum', ''), 'grams': form.get('grams', ''), 'key': form.get('key', '')}
    try:
        if not form.get('drum'):
            raise TrialError('BAD_ISSUE')
        try:
            grams = int(form.get('grams', ''))
        except (TypeError, ValueError):
            raise TrialError('BAD_ISSUE') from None
        record, fresh, after = commit(current_app.config['LEDGER'], material or load(mode), form.get('drum'),
                                      grams, form.get('key'),
                                      lambda data, limits: process(data, 'stock', limits))
        reply.update(ok=True, created=fresh, issue=record, after=after and after['reuse'])
    except TrialError as exc:
        reply.update(ok=False, error=exc.code)
    return reply


@station.route('/', methods=['GET', 'POST'])
@station.route('/trial/<stage>', methods=['GET', 'POST'])
def review(stage='stock'):
    if stage not in LABELS:
        abort(404)
    mode = request.values.get('sample', 'dirty')
    data, pack, error, record, entries, fresh, issued = {}, None, None, None, [], False, None
    root = current_app.config['ARCHIVE']
    material = {}
    try:
        material = materials(mode)
        if stage in ('batches', 'certificate'):
            if stage == 'batches' and request.method == 'POST':
                record, fresh = preserve(root, material, ledger_totals(current_app.config['LEDGER']))
            entries = history(root)
            if stage == 'certificate' and (entries or request.args.get('batch')):
                pack = issue(read(root, request.args.get('batch') or entries[0]['batch_id']))
        elif stage in ('reuse', 'stock') and request.method == 'POST' and request.form.get('drum'):
            issued = issue_feedback(mode, material)
            data = process(material, stage, ledger_totals(current_app.config['LEDGER']))
        else:
            data = process(material, stage, ledger_totals(current_app.config['LEDGER']))
    except TrialError as exc:
        error = exc.code
    form_plan = request.form if mode == 'custom' else material.get('plan', {})
    form_assays = request.form.get('assays', '') if mode == 'custom' else material.get('assays', '')
    form_proposal = request.form.get('proposal', '{}') if mode == 'custom' else json.dumps(material.get('proposal', {}))
    form_drums = request.form.get('drums', '') if mode == 'custom' else json.dumps(material.get('drums', []), ensure_ascii=False)
    issue_form = request.form if request.method == 'POST' else {'key': '', 'drum': '', 'grams': ''}
    return render_template('station.html', stages=STAGES, labels=LABELS, fields=PLAN_FIELDS,
                           issue_fields=ISSUE_FIELDS, revision=REVISION, stage=stage, mode=mode, data=data,
                           error=error, form_plan=form_plan, form_assays=form_assays, form_proposal=form_proposal,
                           form_drums=form_drums, record=record, fresh=fresh, entries=entries, pack=pack,
                           issued=issued, ledger=ledger_rows(current_app.config['LEDGER']), issue_form=issue_form)
