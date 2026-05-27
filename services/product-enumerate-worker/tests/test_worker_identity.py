from __future__ import annotations

from src.worker import _runtime_worker_id


def test_runtime_worker_id_preserves_configured_prefix():
    worker_id = _runtime_worker_id("product-enumerate-worker")
    assert worker_id.startswith("product-enumerate-worker-")


def test_runtime_worker_id_is_unique_per_call():
    first = _runtime_worker_id("product-enumerate-worker")
    second = _runtime_worker_id("product-enumerate-worker")
    assert first != second
