from .errors import TrialError
from .modules.assay.service import receive
from .modules.dry.service import convert
from .modules.formula.contract import normalize
from .modules.formula.service import inspect
from .modules.blend.service import select
from .modules.stock.balance import reconcile
from .modules.reuse.model import parse_drums
from .modules.reuse.service import evaluate
from .modules.reuse.units import from_reuse


def process(material, stage='archive', limits=None):
    if len(material['assays']) > 250_000:
        raise TrialError('ASSAYS_TOO_LARGE', 413)
    assays = receive(material['assays'])
    result = {'assay': assays}
    if stage == 'assay':
        return result
    plan = normalize(material.get('plan'))
    dry = convert(assays['lots'], plan['as_of'])
    drums = parse_drums(material.get('drums'))
    reuse = evaluate(drums, dry['lots'], plan['as_of'], limits=limits or {})
    dry = {**dry, 'lots': reuse['lots'], 'reuse': reuse, 'drum_dry_g': reuse['drum_dry_g'],
           'eligible_dry_g': reuse['eligible_dry_g']}
    result['dry'], result['reuse'], result['plan'] = dry, reuse, plan
    if stage in ('dry', 'reuse'):
        return result
    if stage in ('formula', 'archive'):
        result['formula'] = inspect(plan, reuse['lots'], material.get('proposal', {}), reuse['drums'])
    if stage == 'formula':
        return result
    result['blend'] = select(plan, from_reuse(reuse))
    if stage == 'blend':
        return result
    result['stock'] = reconcile(plan, reuse['lots'], result['blend'], reuse)
    return result
