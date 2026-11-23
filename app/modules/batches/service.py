from time import perf_counter

from app.pipeline import process
from .seal import manifest
from .storage import write


def preserve(root, material, ledger=None):
    """留档与预览共用同一账本上限，保证证据与试算页一致。"""
    started = perf_counter()
    results = process(material, limits=ledger or {})
    return write(root, manifest(material, results, started, ledger))
