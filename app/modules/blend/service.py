from app.config import MAX_LOTS
from app.errors import TrialError
from app.modules.formula.metrics import measurements, weigh
from .search import search


def select(plan, units):
    available = [row for row in units if row['status'] == 'ELIGIBLE' and row['available_g'] >= plan['step_g']]
    if len(available) > MAX_LOTS:
        raise TrialError('TOO_MANY_LOTS')
    capacity = sum(lot['available_g'] // plan['step_g'] * plan['step_g'] for lot in available)
    if capacity < plan['target_g']:
        return {'status': 'INSUFFICIENT_STEP_STOCK', 'allocation': {}, 'batch_count': 0, 'step_capacity_g': capacity, 'visited': 0}
    allocation, visited = search(available, plan)
    if allocation is None:
        return {'status': 'QUALITY_INFEASIBLE', 'allocation': {}, 'batch_count': 0, 'step_capacity_g': capacity, 'visited': visited}
    selected = {lot['lot']: weight for lot, weight in zip(available, allocation) if weight}
    dry, moment = weigh(available, allocation)
    lines = [{'lot': lot['lot'], 'kind': lot['kind'], 'line': lot['line'], 'expires': lot['expires'],
              'grams': weight, 'moisture_bp': lot['moisture_bp'], 'gel_msag': lot['gel_msag']}
             for lot, weight in zip(available, allocation) if weight]
    return {'status': 'FEASIBLE', 'allocation': selected, 'batch_count': len(selected), 'step_capacity_g': capacity,
            'visited': visited, 'units': [{'lot': lot['lot'], 'kind': lot['kind']} for lot in available],
            'lines': lines, **measurements(dry, moment)}
