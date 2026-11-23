from app.errors import TrialError
from app.modules.dry.weights import dry_units
from .metrics import measurements, quality


def _resolve(lot_id, known, drums):
    """批号原批；合桶按整桶复验值参与干物与凝胶，桶号可直接写进提案。"""
    lot = known.get(lot_id)
    if lot is not None:
        return {'lot': lot['lot'], 'line': lot['line'], 'kind': 'LOT', 'status': lot['status'],
                'stock_g': lot['available_g'], 'moisture_bp': lot['moisture_bp'], 'gel_msag': lot['gel_msag']}
    drum = drums.get(lot_id)
    if drum is not None:
        return {'lot': drum['drum'], 'line': None, 'kind': 'DRUM',
                'status': 'ELIGIBLE' if drum['reusable'] else drum['status'],
                'drum_status': drum['status'], 'stock_g': drum['issuable_g'],
                'moisture_bp': drum['recheck']['moisture_bp'],
                'gel_msag': drum['recheck']['gel_msag'], 'blockers': drum['blockers']}
    return None


def inspect(plan, lots, proposal, drums=()):
    if not isinstance(proposal, dict) or any(type(v) is not int or v < 0 or v > 10**9 for v in proposal.values()):
        raise TrialError('BAD_PROPOSAL')
    known = {row['lot']: row for row in lots}
    drum_by_id = {row['drum']: row for row in drums}
    findings, dry, moment, mass = [], 0, 0, 0
    for lot_id, weight in proposal.items():
        if not weight:
            continue
        mass += weight
        unit = _resolve(lot_id, known, drum_by_id)
        codes = []
        if unit is None:
            codes.append('LOT_NOT_ACCEPTED')
        else:
            if unit['status'] != 'ELIGIBLE':
                codes.append(unit['status'])
            if weight > unit['stock_g']:
                codes.append('OVER_STOCK')
            if unit['kind'] == 'DRUM':
                codes.extend(f'BLOCKED_{code}' for code in unit['blockers'])
            amount = dry_units(weight, unit['moisture_bp'])
            dry += amount
            moment += amount * unit['gel_msag']
        if weight % plan['step_g']:
            codes.append('OFF_STEP')
        findings.append({'lot': lot_id, 'line': unit['line'] if unit else None,
                         'kind': unit['kind'] if unit else None, 'grams': weight, 'codes': codes})
    checks = quality(plan, mass, dry, moment)
    return {'can_make': all(checks.values()) and not any(row['codes'] for row in findings),
            'mass_g': mass, **measurements(dry, moment), 'checks': checks, 'findings': findings}
