"""合桶回用的判定与计量。

判定顺序固定为：来源可核对 → 复验结论 → 原批有效期。整桶是一个不可拆分的
物理单位，复验合格也不能越过任何一份来源原批的有效期；只要一份来源批在
试配日已到期，整桶即不可领（`EXPIRED_SOURCE`），可领量为 0。

合入桶的料从原批库存转出一次（`drummed_g`），此后只在桶上计量；原批余量
不再把这份料算作可领，避免合桶前后重复计数。
"""
from app.modules.dry.weights import as_grams, dry_units

REUSABLE = 'REUSABLE'
REJECTED = 'REJECTED'
EXPIRED_SOURCE = 'EXPIRED_SOURCE'
INVALID = 'INVALID'


def _source_rows(drum, known, as_of):
    rows, issues, expired = [], [], []
    for source in drum['sources']:
        lot = known.get(source['lot'])
        if lot is None:
            rows.append({**source, 'expires': None, 'status': 'UNKNOWN_SOURCE'})
            issues.append('UNKNOWN_SOURCE')
            continue
        blocked = lot['expires'] < as_of
        rows.append({**source, 'expires': lot['expires'], 'status': 'EXPIRED' if blocked else lot['status']})
        if blocked:
            expired.append(source['lot'])
    return rows, issues, sorted(set(expired))


def _trace(sources, grams):
    """把领用克重按来源克重比例分摊到原批，整数最大余数法，合计恰为 grams。"""
    total = sum(row['grams'] for row in sources)
    if not grams or not total:
        return [{'lot': row['lot'], 'grams': 0} for row in sources]
    shares = []
    for row in sources:
        exact = grams * row['grams']
        shares.append([row['lot'], exact // total, exact % total])
    handed = sum(share[1] for share in shares)
    order = sorted(range(len(shares)), key=lambda i: (-shares[i][2], sources[i]['lot']))
    for i in order[:grams - handed]:
        shares[i][1] += 1
    return [{'lot': lot, 'grams': amount} for lot, amount, _ in shares]


def evaluate(drums, lots, as_of, limits=None):
    """返回回用判定、可领量与扣减合桶来源后的原批余量。

    `limits` 是跨单领用账本（批号/桶号 → 已领克重），只影响可领量，不改判定。
    """
    limits = limits or {}
    known = {lot['lot']: lot for lot in lots}
    remaining = {lot['lot']: lot['stock_g'] for lot in lots}
    rows, drum_dry = [], 0

    for drum in sorted(drums, key=lambda item: (item['created'] or '', item['drum'])):
        sources, issues, expired = _source_rows(drum, known, as_of)
        if drum['drum'] in known:
            status, issues = INVALID, issues + ['LOT_ID_COLLISION']
        elif issues:
            status = INVALID
        elif any(source['grams'] > remaining.get(source['lot'], 0) for source in drum['sources']):
            status, issues = INVALID, issues + ['OVER_SOURCE']
        elif drum['recheck']['verdict'] != 'PASS':
            status = REJECTED
        elif expired:
            status = EXPIRED_SOURCE
        else:
            status = REUSABLE

        # 已合入桶的料只从原批转出一次；来源无法核对时不臆测扣减。
        if status != INVALID:
            for source in drum['sources']:
                remaining[source['lot']] -= source['grams']
        for row in sources:
            row['remaining_g'] = remaining.get(row['lot'], 0)

        issued = min(max(limits.get(drum['drum'], 0), 0), drum['weight_g'])
        issuable = drum['weight_g'] - issued if status == REUSABLE else 0
        blocked = 0 if status == REUSABLE else drum['weight_g']
        dry_u = dry_units(issuable, drum['recheck']['moisture_bp'])
        drum_dry += dry_u
        expires = min((row['expires'] for row in sources if row['expires']), default=None)
        rows.append({'drum': drum['drum'], 'created': drum['created'], 'weight_g': drum['weight_g'],
                     'sources': sources, 'recheck': drum['recheck'], 'verdict': drum['recheck']['verdict'],
                     'status': status, 'reusable': status == REUSABLE, 'issued_g': issued,
                     'issuable_g': issuable, 'blocked_g': blocked,
                     'effective_expires': expires, 'blockers': expired, 'issues': sorted(set(issues)),
                     'dry_stock_g': as_grams(dry_u)})

    adjusted, consumed = [], 0
    for lot in lots:
        moved = lot['stock_g'] - remaining[lot['lot']]
        used = min(max(limits.get(lot['lot'], 0), 0), max(remaining[lot['lot']], 0))
        consumed += moved
        row = {**lot, 'stock_original_g': lot['stock_g'], 'drummed_g': moved,
               'stock_g': remaining[lot['lot']], 'issued_g': used,
               'available_g': remaining[lot['lot']] - used}
        dry_u = dry_units(max(row['available_g'], 0), row['moisture_bp'])
        row['dry_stock_u'], row['dry_stock_g'] = dry_u, as_grams(dry_u)
        adjusted.append(row)

    lot_dry = sum(row['dry_stock_u'] for row in adjusted if row['status'] == 'ELIGIBLE')
    by_status = {name: sum(1 for row in rows if row['status'] == name)
                 for name in (REUSABLE, REJECTED, EXPIRED_SOURCE, INVALID)}
    transferred = sum(row['weight_g'] for row in rows if row['status'] != INVALID)
    return {'as_of': as_of, 'drums': rows, 'drum_count': len(rows), 'counts': by_status,
            'issuable_g': sum(row['issuable_g'] for row in rows),
            'blocked_g': sum(row['blocked_g'] for row in rows),
            'drum_weight_g': sum(row['weight_g'] for row in rows), 'drummed_g': consumed,
            'lots': adjusted, 'drum_dry_g': as_grams(drum_dry),
            'eligible_dry_g': as_grams(lot_dry + drum_dry),
            'balanced': transferred == consumed}


def trace_issue(drum, grams):
    """领用对账：把一次合桶领用追溯到来源原批。"""
    return _trace(drum['sources'], grams)
