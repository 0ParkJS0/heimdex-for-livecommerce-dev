"""Tests for app.cli.backfill_ocr_gating.

Scope: the scroll + diff + bulk-update loop. We mock the OpenSearch client
entirely — the goal is to verify decision logic (what gets updated, what
gets skipped as already-clean) and that --dry-run never writes.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.cli.backfill_ocr_gating import _backfill


def _hit(doc_id: str, raw: str, count: int | None = None) -> dict:
    src = {
        "org_id": "00000000-0000-0000-0000-000000000001",
        "video_id": "vid1",
        "scene_id": f"vid1_{doc_id}",
        "ocr_text_raw": raw,
    }
    if count is not None:
        src["ocr_char_count"] = count
    return {"_id": doc_id, "_source": src, "sort": [int(doc_id.split("_")[-1])]}


def _make_client_with_hits(*batches: list[dict]) -> MagicMock:
    """Return a SceneSearchClient mock that yields one batch per .search() call,
    then an empty hits list to end the scroll."""
    client = MagicMock()
    client.alias_name = "heimdex_scenes"
    client.client = MagicMock()
    responses = [{"hits": {"hits": b}} for b in batches] + [
        {"hits": {"hits": []}}
    ]
    client.client.search = AsyncMock(side_effect=responses)
    client.bulk_partial_update_scenes = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_writes_only_when_processing_changes_text():
    """Already-clean rows are skipped; only dirty rows are written."""
    # Row A: pre-gate noise that the gate will reject (G3)              -> cleared
    # Row B: legacy row where stored char_count = len(norm) disagrees
    #        with the contract's len(raw_gated) — text unchanged but
    #        count must be rewritten                                     -> changed
    # Row C: already clean — gated text == raw, count matches            -> skipped
    clean_text = "라이브커머스 50% 할인"
    legacy_text = "BIG SALE"
    hits = [
        _hit("scene_1", "!!! @@@ ###", count=11),                       # -> cleared
        _hit("scene_2", legacy_text, count=len(legacy_text) - 2),       # -> changed (count off)
        _hit("scene_3", clean_text, count=len(clean_text)),             # -> skipped
    ]
    client = _make_client_with_hits(hits)

    with patch("app.modules.search.scene_client.SceneSearchClient", return_value=client):
        await _backfill(
            limit=0,
            batch_size=10,
            dry_run=False,
            org_id=None,
        )

    client.bulk_partial_update_scenes.assert_awaited_once()
    sent = client.bulk_partial_update_scenes.await_args[0][0]
    ids = [doc_id for doc_id, _ in sent]
    assert "scene_1" in ids
    assert "scene_2" in ids
    assert "scene_3" not in ids   # idempotent skip

    partials = {doc_id: partial for doc_id, partial in sent}
    # Noise-rejected row -> empty triple
    assert partials["scene_1"]["ocr_text_raw"] == ""
    assert partials["scene_1"]["ocr_char_count"] == 0
    # Count-fixed row -> text unchanged, count now matches len(raw_gated)
    assert partials["scene_2"]["ocr_text_raw"] == legacy_text
    assert partials["scene_2"]["ocr_char_count"] == len(legacy_text)


@pytest.mark.asyncio
async def test_dry_run_never_writes():
    # Use noise text so the row is genuinely dirty (would be cleared by the
    # gate) — proves dry-run skips the write regardless of how dirty.
    hits = [_hit("scene_1", "!!! @@@ ###", count=11)]
    client = _make_client_with_hits(hits)
    with patch("app.modules.search.scene_client.SceneSearchClient", return_value=client):
        await _backfill(
            limit=0,
            batch_size=10,
            dry_run=True,
            org_id=None,
        )
    client.bulk_partial_update_scenes.assert_not_awaited()


@pytest.mark.asyncio
async def test_org_filter_added_to_query():
    """When --org is set, the org_id term should be in the OpenSearch query."""
    client = _make_client_with_hits([])
    with patch("app.modules.search.scene_client.SceneSearchClient", return_value=client):
        await _backfill(
            limit=0,
            batch_size=10,
            dry_run=True,
            org_id="0123-org-uuid",
        )
    body = client.client.search.await_args.kwargs["body"]
    must_clauses = body["query"]["bool"]["must"]
    assert any(
        c.get("term", {}).get("org_id") == "0123-org-uuid" for c in must_clauses
    )


@pytest.mark.asyncio
async def test_limit_stops_scan_early():
    """--limit caps how many docs the loop touches across batches."""
    batch_a = [_hit(f"scene_{i}", "!!! @@@", count=7) for i in range(1, 6)]
    batch_b = [_hit(f"scene_{i}", "!!! @@@", count=7) for i in range(6, 11)]
    client = _make_client_with_hits(batch_a, batch_b)
    with patch("app.modules.search.scene_client.SceneSearchClient", return_value=client):
        await _backfill(
            limit=3,
            batch_size=5,
            dry_run=False,
            org_id=None,
        )
    # Only the first 3 docs of batch_a should reach the update buffer
    sent = client.bulk_partial_update_scenes.await_args[0][0]
    assert len(sent) == 3


@pytest.mark.asyncio
async def test_second_run_after_backfill_is_noop():
    """After backfill applies once, a second pass over the SAME docs should
    detect them as already-clean and write nothing. Guards against an
    idempotency regression in the diff check."""
    # Simulate a row that's already been through process_ocr_text:
    # use plain text that survives the pipeline verbatim with matching count.
    clean_text = "정상 텍스트입니다"
    hits = [_hit("scene_1", clean_text, count=len(clean_text))]
    client = _make_client_with_hits(hits)
    with patch("app.modules.search.scene_client.SceneSearchClient", return_value=client):
        await _backfill(
            limit=0,
            batch_size=10,
            dry_run=False,
            org_id=None,
        )
    client.bulk_partial_update_scenes.assert_not_awaited()
