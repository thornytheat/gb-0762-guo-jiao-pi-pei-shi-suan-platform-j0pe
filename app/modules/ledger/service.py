"""领用账本：并发串行化、幂等提交与原子落盘。

一单领用 = 一个按 `key` 幂等的内容寻址文件。提交时先拿目录级文件锁，再做
「读全账本 → 合桶余量校验 → 原子发布」，因此两单同时提交不会领超同一桶。
失败的单不落盘，重试不会重复扣余料；同 key 重放返回既有记录而不是再扣一次。
"""
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.errors import TrialError
from app.modules.batches.seal import canonical, sha
from app.modules.reuse.service import trace_issue


@contextmanager
def _locked(root):
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / '.lock', 'a+b') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def rows(root):
    directory = Path(root)
    if not directory.is_dir():
        return []
    records = []
    for path in directory.glob('*.json'):
        try:
            records.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    records.sort(key=lambda record: (record.get('created_at', ''), record.get('issue_id', '')))
    return records


def totals(root):
    """桶号 → 已领克重，作为下一次评估的跨单上限。"""
    result = {}
    for record in rows(root):
        result[record['drum']] = result.get(record['drum'], 0) + record['grams']
    return result


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128 or any(ord(ch) < 32 for ch in value.strip()):
        raise TrialError('BAD_ISSUE')
    return value.strip()


def _grams(value):
    if type(value) is not int or not 0 < value <= 10_000_000:
        raise TrialError('BAD_ISSUE')
    return value


def _fingerprint(material):
    return sha(canonical({key: material.get(key) for key in ('assays', 'plan', 'proposal', 'drums')}))


def commit(root, material, drum_id, grams, key, build):
    """build(material, limits) -> 评估结果（至少含 reuse）；在锁内评估。"""
    drum_id, key, grams = _text(drum_id), _text(key), _grams(grams)
    payload = {'drum': drum_id, 'grams': grams, 'as_of': (material.get('plan') or {}).get('as_of'),
               'material_sha256': _fingerprint(material)}
    issue_id = sha(canonical([key, payload]))
    with _locked(root) as directory:
        existing = next((row for row in rows(directory) if row.get('key') == key), None)
        if existing is not None:
            if existing.get('issue_id') != issue_id:
                raise TrialError('IDEMPOTENCY_CONFLICT', 409)
            return existing, False, build(material, totals(directory))
        limits = totals(directory)
        result = build(material, limits)
        drum = next((row for row in result['reuse']['drums'] if row['drum'] == drum_id), None)
        if drum is None:
            raise TrialError('DRUM_NOT_FOUND', 404)
        if drum['status'] != 'REUSABLE':
            raise TrialError('DRUM_NOT_REUSABLE', 422)
        if grams > drum['issuable_g']:
            raise TrialError('OVER_DRUM', 409)
        after = build(material, {**limits, drum_id: limits.get(drum_id, 0) + grams})
        record = {'issue_id': issue_id, 'key': key, 'payload': payload, 'drum': drum_id,
                  'grams': grams, 'as_of': payload['as_of'], 'verdict': drum['verdict'],
                  'effective_expires': drum['effective_expires'], 'weight_g': drum['weight_g'],
                  'sources': drum['sources'], 'trace': trace_issue(drum, grams),
                  'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        target = directory / f'{issue_id}.json'
        with NamedTemporaryFile(dir=directory, delete=False) as file:
            temp = Path(file.name)
            try:
                file.write(canonical(record))
                file.flush()
                os.fsync(file.fileno())
                try:
                    os.link(temp, target)
                except FileExistsError:
                    return json.loads(target.read_text(encoding='utf-8')), False, after
            finally:
                temp.unlink(missing_ok=True)
        return record, True, after
