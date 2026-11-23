"""回用单元：把可领合桶与可领原批统一成寻优/验方/对账的库存单元。"""


def from_reuse(reuse):
    result = []
    for lot in reuse['lots']:
        if lot['status'] != 'ELIGIBLE' or lot['available_g'] <= 0:
            continue
        result.append({**lot, 'kind': 'LOT'})
    for drum in reuse['drums']:
        if not drum['reusable'] or drum['issuable_g'] <= 0:
            continue
        result.append({'lot': drum['drum'], 'kind': 'DRUM', 'line': None, 'expires': drum['effective_expires'],
                       'stock_g': drum['issuable_g'], 'available_g': drum['issuable_g'], 'status': 'ELIGIBLE',
                       'moisture_bp': drum['recheck']['moisture_bp'], 'gel_msag': drum['recheck']['gel_msag'],
                       'dry_stock_g': drum['dry_stock_g'], 'sources': drum['sources']})
    return sorted(result, key=lambda row: (row['expires'], row['lot']))
