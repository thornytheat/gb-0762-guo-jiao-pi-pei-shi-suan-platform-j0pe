"""合桶回用：整桶复验单的规范化。

一个桶由若干来源批的剩余料合并而成，复验值属于整桶。来源批号、克重、
复验水分/凝胶与判定缺一不可；跨字段的库存校验留给 service 层。
"""
from app.errors import TrialError
from app.modules.assay.units import day, scaled

SOURCES = {'lot', 'grams'}
RECHECK = {'moisture_pct', 'gel_sag', 'verdict'}
DRUM = {'drum', 'created', 'sources', 'recheck'}
VERDICTS = {'PASS': 'PASS', 'FAIL': 'FAIL', '合格': 'PASS', '不合格': 'FAIL'}
MAX_SOURCE_G = 10_000_000


def _text(value):
    if not isinstance(value, str):
        raise TrialError('BAD_DRUM')
    text = value.strip()
    if not text or len(text) > 64 or any(ord(ch) < 32 for ch in text):
        raise TrialError('BAD_DRUM')
    return text


def _amount(value, factor, maximum):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise TrialError('BAD_DRUM')
    try:
        return scaled(str(value), factor, maximum)
    except ValueError:
        raise TrialError('BAD_DRUM') from None


def _date(value):
    try:
        return day(value)
    except (TypeError, ValueError):
        raise TrialError('BAD_DRUM') from None


def parse_drum(raw):
    if not isinstance(raw, dict) or set(raw) - DRUM or not {'drum', 'sources', 'recheck'} <= set(raw):
        raise TrialError('BAD_DRUM')
    drum = _text(raw['drum'])
    created = _date(raw['created']) if raw.get('created') is not None else None

    if not isinstance(raw['sources'], list) or not raw['sources']:
        raise TrialError('BAD_DRUM')
    sources = {}
    for item in raw['sources']:
        if not isinstance(item, dict) or set(item) != SOURCES:
            raise TrialError('BAD_DRUM')
        lot = _text(item['lot'])
        grams = _amount(item['grams'], 1, MAX_SOURCE_G)
        if not grams:
            raise TrialError('BAD_DRUM')
        sources[lot] = sources.get(lot, 0) + grams
        if sources[lot] > MAX_SOURCE_G:
            raise TrialError('BAD_DRUM')
    ordered = [{'lot': lot, 'grams': sources[lot]} for lot in sorted(sources)]

    recheck = raw['recheck']
    if not isinstance(recheck, dict) or set(recheck) != RECHECK:
        raise TrialError('BAD_DRUM')
    if not isinstance(recheck['verdict'], str):
        raise TrialError('BAD_DRUM')
    verdict = VERDICTS.get(recheck['verdict'].strip().upper())
    if not verdict:
        raise TrialError('BAD_DRUM')
    return {'drum': drum, 'created': created, 'sources': ordered,
            'recheck': {'moisture_bp': _amount(recheck['moisture_pct'], 100, 9999),
                        'gel_msag': _amount(recheck['gel_sag'], 1000, 500_000),
                        'verdict': verdict},
            'weight_g': sum(row['grams'] for row in ordered)}


def parse_drums(raw):
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise TrialError('BAD_DRUMS')
    parsed, seen = [], set()
    for item in raw:
        drum = parse_drum(item)
        if drum['drum'] in seen:
            raise TrialError('DUPLICATE_DRUM')
        seen.add(drum['drum'])
        parsed.append(drum)
    return parsed
