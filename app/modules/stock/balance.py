from app.modules.reuse.service import trace_issue


def reconcile(plan, lots, solution, reuse=None):
    """领用与余量核算。

    合入桶的料先从原批转出（drummed_g），再在桶行领用；期初只按原批计一次，
    守恒式为 期初 = 累计领用 + 期末。桶行领用附来源分摊，能追到原批。
    """
    picks = solution['allocation']
    drums = {row['drum']: row for row in (reuse or {}).get('drums', [])}
    rows = []
    for lot in lots:
        prior = lot.get('issued_g', 0)
        issued = picks.get(lot['lot'], 0)
        code = 'ISSUED' if issued else lot['status']
        if not issued and lot['status'] == 'ELIGIBLE':
            code = 'BELOW_STEP' if lot['available_g'] < plan['step_g'] else 'NOT_SELECTED'
        rows.append({'lot': lot['lot'], 'kind': 'LOT', 'line': lot['line'], 'expires': lot['expires'],
                     'begin_g': lot['stock_original_g'], 'drummed_g': lot['drummed_g'], 'prior_g': prior,
                     'issued_g': issued, 'end_g': lot['stock_g'] - prior - issued, 'code': code})
    for name, drum in drums.items():
        if drum['status'] == 'INVALID':
            continue
        prior = drum['issued_g']
        issued = picks.get(name, 0)
        code = 'ISSUED' if issued else drum['status']
        rows.append({'lot': name, 'kind': 'DRUM', 'line': None, 'expires': drum['effective_expires'],
                     'begin_g': drum['weight_g'], 'drummed_g': drum['weight_g'], 'prior_g': prior,
                     'issued_g': issued, 'end_g': drum['weight_g'] - prior - issued, 'code': code,
                     'recheck': drum['recheck'], 'sources': drum['sources'],
                     'trace': trace_issue(drum, issued) if issued else []})
    lot_rows = [row for row in rows if row['kind'] == 'LOT']
    begin = sum(row['begin_g'] for row in lot_rows)
    drummed = sum(row['drummed_g'] for row in lot_rows)
    issued = sum(row['issued_g'] for row in rows)
    prior = sum(row['prior_g'] for row in rows)
    end = sum(row['end_g'] for row in rows)
    target = plan['target_g']
    shortage = target - issued
    return {'target_g': target, 'begin_g': begin, 'drummed_g': drummed,
            'drum_begin_g': sum(row['begin_g'] for row in rows if row['kind'] == 'DRUM'),
            'issued_g': issued, 'prior_g': prior, 'cumulative_issued_g': issued + prior,
            'lot_issued_g': sum(row['issued_g'] for row in lot_rows),
            'drum_issued_g': sum(row['issued_g'] for row in rows if row['kind'] == 'DRUM'),
            'end_g': end, 'shortage_g': shortage,
            'balanced': begin == issued + prior + end
            and 0 <= shortage <= target and all(row['end_g'] >= 0 for row in rows), 'rows': rows}
