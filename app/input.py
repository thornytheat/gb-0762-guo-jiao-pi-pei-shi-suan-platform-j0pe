import json
from flask import request

from .config import DATA
from .errors import TrialError

MATERIAL_FIELDS = {'assays', 'plan', 'proposal', 'drums'}


def load(mode):
    if mode not in ('dirty', 'clean', 'reuse'):
        raise TrialError('UNKNOWN_SAMPLE', 404)
    directory = DATA / mode
    material = {'assays': (directory / 'assays.csv').read_text(encoding='utf-8'),
                **json.loads((directory / 'trial.json').read_text(encoding='utf-8'))}
    drums = directory / 'drums.json'
    if drums.exists():
        material['drums'] = json.loads(drums.read_text(encoding='utf-8'))
    return material


def from_request(extra=frozenset()):
    """解析试配资料；`extra` 让领用单字段与资料同体提交。"""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise TrialError('JSON_REQUIRED', 400)
    names = MATERIAL_FIELDS | {'sample'} | set(extra)
    if set(body) - names:
        raise TrialError('UNKNOWN_REQUEST_FIELD', 400)
    material = {key: value for key, value in body.items() if key in MATERIAL_FIELDS}
    if 'sample' in body:
        return {**load(body['sample']), **material}
    if not isinstance(body.get('assays'), str):
        raise TrialError('ASSAYS_REQUIRED', 400)
    return material
