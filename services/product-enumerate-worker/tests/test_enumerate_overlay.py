"""Worker overlay-enumeration tests (S3 of the overlay migration).

Covers the two-pass orchestration added to ``handle_enumerate_job``:

* ``mode="vision+overlay"`` runs BOTH passes in one worker invocation,
  sharing the keyframe fetch + the loaded SigLIP2 + the loaded OWLv2,
  and emits BOTH vision-source and overlay-source catalog rows in a
  SINGLE complete callback.
* ``mode="overlay"`` runs only the overlay pass.
* ``mode="vision"`` (default / legacy) runs only the vision pass — the
  byte-identical regression is asserted here too.

The model boundaries (OWLv2 / gpt-4o-mini / SigLIP2) and the network
(S3 / keyframe-fetch / ApiClient) are mocked; the test exercises the
real orchestration in ``handle_enumerate_job`` (which pass(es) run, how
the per-row ``enumeration_source`` is stamped, that the keyframe fetch
happens once).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from heimdex_media_pipelines.product_enum import CanonicalProduct
from PIL import Image

from src.settings import WorkerSettings
from src.tasks.enumerate import handle_enumerate_job


def _settings() -> WorkerSettings:
    return WorkerSettings(
        product_v2_enabled=True,
        sqs_product_enumerate_queue_url="https://sqs/q",
        drive_internal_api_key="test-token",
        drive_api_base_url="http://api:8000",
        drive_s3_bucket="test-bucket",
        openai_api_key="sk-test",
    )


def _vlm_client() -> MagicMock:
    """A stand-in for ``OpenAIVlmClient`` — the overlay pass reads
    ``_client`` / ``owlv2_processor`` / ``owlv2_session`` /
    ``owlv2_device`` off it to build its adapters, but those adapters
    are never invoked because ``enumerate_products_overlay`` is patched."""
    vlm = MagicMock()
    vlm._client = MagicMock()
    vlm.owlv2_processor = MagicMock()
    vlm.owlv2_session = MagicMock()
    vlm.owlv2_device = MagicMock()
    return vlm


def _canonical(label: str, *, rejected: str | None = None) -> CanonicalProduct:
    return CanonicalProduct(
        canonical_scene_id="gd_test_scene_001",
        canonical_frame_idx=10000,
        canonical_bbox_xywh=(10, 20, 100, 150),
        canonical_crop=Image.new("RGB", (100, 150), (200, 100, 50)),
        llm_label=label,
        siglip2_embedding=[0.1] * 768,
        enumeration_confidence=0.8,
        prominence_score=0.4,
        cluster_size=2,
        rejected_reason=rejected,
    )


def _message(*, mode: str) -> dict:
    return {
        "type": "product.enumerate_job",
        "job_id": str(uuid4()),
        "org_id": str(uuid4()),
        "video_id": str(uuid4()),
        "requested_by_user_id": str(uuid4()),
        "enumeration_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
        "max_keyframes": 60,
        "enumeration_mode": mode,
    }


def _one_keyframe():
    from heimdex_media_pipelines.product_enum import SceneKeyframe

    return [
        SceneKeyframe(
            scene_id="gd_test_scene_001",
            frame_idx=10000,
            image=Image.new("RGB", (640, 480), (128, 128, 128)),
        )
    ]


def _run(message: dict):
    """Drive ``handle_enumerate_job`` with every model/network boundary
    mocked. Returns the captured ApiClient mock so callers can assert on
    ``complete_enumeration`` / ``fail`` and the patch handles."""
    settings = _settings()
    vlm = _vlm_client()

    api = MagicMock()
    # claim returns the standard tuple-bearing dict; heartbeat/complete
    # return empties — none are asserted on except complete_enumeration.
    api.claim.return_value = {}

    with patch("src.tasks.enumerate.ApiClient", return_value=api), \
        patch("src.tasks.enumerate._fetch_keyframes") as fetch, \
        patch("src.tasks.enumerate.load_siglip", return_value=MagicMock()), \
        patch("src.tasks.enumerate.embed_pil_image_batch", return_value=[[0.1] * 768]), \
        patch("src.tasks.enumerate.enumerate_products") as vision_fn, \
        patch("src.tasks.enumerate.enumerate_products_overlay") as overlay_fn, \
        patch("src.tasks.enumerate._upload_crops_and_build_payload") as upload:
        # ``_fetch_keyframes`` now returns ``(scene_keyframes,
        # ocr_by_scene_id)``; mirror the shape so the overlay path's
        # ``ocr_by_scene_id.get(...)`` lookup resolves cleanly.
        fetch.return_value = (
            _one_keyframe(),
            {"gd_test_scene_001": "29,900 원"},
        )
        # merge_products_by_label is a no-op pass-through for the canned
        # products (label-merge tested elsewhere); leave it real.
        vision_fn.return_value = ([_canonical("핑크 세럼")], 0.01)
        overlay_fn.return_value = ([_canonical("오버레이 카드 상품")], 0.02)

        # The upload helper is the only place ``enumeration_source`` is
        # stamped onto the payload — emulate that faithfully so the
        # complete callback assertion is meaningful.
        def _fake_upload(*, products, enumeration_source, **kwargs):
            return [
                {"llm_label": p.llm_label, "enumeration_source": enumeration_source}
                for p in products
            ]

        upload.side_effect = _fake_upload

        handle_enumerate_job(message=message, settings=settings, vlm_client=vlm)

    return api, fetch, vision_fn, overlay_fn


# =========================================================================
# vision+overlay — both passes, shared fetch, both sources, one callback
# =========================================================================

def test_vision_plus_overlay_emits_both_sources_single_callback():
    api, fetch, vision_fn, overlay_fn = _run(_message(mode="vision+overlay"))

    # Shared keyframe fetch happens exactly once for both passes.
    assert fetch.call_count == 1
    # Both passes ran.
    assert vision_fn.call_count == 1
    assert overlay_fn.call_count == 1
    # Exactly one complete callback.
    assert api.complete_enumeration.call_count == 1
    assert api.fail.call_count == 0

    entries = api.complete_enumeration.call_args.kwargs["catalog_entries"]
    sources = sorted(e["enumeration_source"] for e in entries)
    assert sources == ["overlay", "vision"]


def test_vision_plus_overlay_shares_loaded_owlv2_and_embedder():
    """The overlay pass must reuse the SAME loaded models — assert it was
    given the vlm_client's OWLv2 + the same embedder closure (not a fresh
    load)."""
    _api, _fetch, _vision, overlay_fn = _run(_message(mode="vision+overlay"))
    # enumerate_products_overlay is called with injected adapters + the
    # shared embedder (a callable), proving no second model load.
    kwargs = overlay_fn.call_args.kwargs
    assert "extractor" in kwargs
    assert "owlv2_detector" in kwargs
    assert callable(kwargs["embedder"])


# =========================================================================
# overlay-only
# =========================================================================

def test_overlay_only_skips_vision_pass():
    api, fetch, vision_fn, overlay_fn = _run(_message(mode="overlay"))

    assert fetch.call_count == 1
    assert vision_fn.call_count == 0      # vision pass skipped
    assert overlay_fn.call_count == 1
    assert api.complete_enumeration.call_count == 1

    entries = api.complete_enumeration.call_args.kwargs["catalog_entries"]
    assert [e["enumeration_source"] for e in entries] == ["overlay"]


# =========================================================================
# vision — legacy default, byte-identical single-source behavior
# =========================================================================

def test_vision_default_runs_only_vision_pass():
    api, fetch, vision_fn, overlay_fn = _run(_message(mode="vision"))

    assert fetch.call_count == 1
    assert vision_fn.call_count == 1
    assert overlay_fn.call_count == 0     # overlay pass NOT run
    assert api.complete_enumeration.call_count == 1

    entries = api.complete_enumeration.call_args.kwargs["catalog_entries"]
    assert [e["enumeration_source"] for e in entries] == ["vision"]


def test_missing_mode_field_defaults_to_vision():
    """Old senders omit ``enumeration_mode`` entirely → vision only."""
    msg = _message(mode="vision")
    del msg["enumeration_mode"]
    api, _fetch, vision_fn, overlay_fn = _run(msg)
    assert vision_fn.call_count == 1
    assert overlay_fn.call_count == 0
    entries = api.complete_enumeration.call_args.kwargs["catalog_entries"]
    assert [e["enumeration_source"] for e in entries] == ["vision"]


# =========================================================================
# OverlayProductExtractor — the worker's gpt-4o-mini overlay reader
# =========================================================================

class TestOverlayProductExtractor:
    def _resp(self, content: str, in_tok: int = 700, out_tok: int = 50):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        resp.usage = MagicMock(prompt_tokens=in_tok, completion_tokens=out_tok)
        return resp

    def test_parses_products_and_charges_cost(self):
        from src.overlay_extractor import OverlayProductExtractor

        client = MagicMock()
        client.chat.completions.create.return_value = self._resp(
            '{"products": [{"name": "핑크 세럼", "price": 29900, '
            '"position": "top-left"}]}'
        )
        extractor = OverlayProductExtractor(
            openai_client=client, daily_cap_usd=100.0,
        )
        batch = extractor.extract(
            scene_id="s1", frame_idx=1000,
            image=Image.new("RGB", (100, 100), (200, 200, 200)),
            ocr_text="29900원",
        )
        assert len(batch.extractions) == 1
        ext = batch.extractions[0]
        assert ext.label == "핑크 세럼"
        assert ext.price == 29900
        assert ext.position == "top-left"
        assert batch.cost_usd > 0

    def test_empty_products_returns_empty_batch(self):
        from src.overlay_extractor import OverlayProductExtractor

        client = MagicMock()
        client.chat.completions.create.return_value = self._resp(
            '{"products": []}'
        )
        extractor = OverlayProductExtractor(openai_client=client)
        batch = extractor.extract(
            scene_id="s1", frame_idx=0,
            image=Image.new("RGB", (50, 50)), ocr_text="",
        )
        assert batch.extractions == []

    def test_budget_cap_raises_after_charge(self):
        from src.overlay_extractor import (
            OverlayBudgetExceededError,
            OverlayProductExtractor,
        )

        client = MagicMock()
        client.chat.completions.create.return_value = self._resp(
            '{"products": [{"name": "X"}]}', in_tok=10_000_000, out_tok=0,
        )
        # ~$1.50 for the call; cap of $0.01 trips immediately.
        extractor = OverlayProductExtractor(
            openai_client=client, daily_cap_usd=0.01,
        )
        import pytest

        with pytest.raises(OverlayBudgetExceededError):
            extractor.extract(
                scene_id="s1", frame_idx=0,
                image=Image.new("RGB", (50, 50)), ocr_text="",
            )


# =========================================================================
# WorkerOwlV2Detector — normalised-xyxy adapter over the loaded OWLv2
# =========================================================================

class TestWorkerOwlV2Detector:
    def test_returns_normalised_xyxy_detections(self):
        import numpy as np

        from src.overlay_owlv2_adapter import WorkerOwlV2Detector

        # Mock the processor: __call__ returns the np tensors the ONNX
        # session expects; post_process returns one box in ``sent`` px.
        processor = MagicMock()
        processor.return_value = {
            "input_ids": np.zeros((1, 2), dtype=np.int64),
            "attention_mask": np.ones((1, 2), dtype=np.int64),
            "pixel_values": np.zeros((1, 3, 4, 4), dtype=np.float32),
        }

        class _T:
            def __init__(self, data):
                self._data = data

            def detach(self):
                return self

            def cpu(self):
                return self

            def tolist(self):
                return self._data

        # Frame is 200x100 (w x h); a box at (50, 25)-(150, 75) px should
        # normalise to (0.25, 0.25)-(0.75, 0.75).
        processor.post_process_grounded_object_detection.return_value = [
            {
                "scores": _T([0.9]),
                "boxes": _T([[50.0, 25.0, 150.0, 75.0]]),
                "labels": _T([0]),
            }
        ]
        session = MagicMock()
        session.run.return_value = (
            np.zeros((1, 1, 1), dtype=np.float32),
            np.zeros((1, 1, 4), dtype=np.float32),
        )

        detector = WorkerOwlV2Detector(
            processor=processor, session=session, device=MagicMock(),
            max_image_side=960,
        )
        # 200 wide, 100 tall BGR frame (<= 960 so no resize; sent == orig).
        frame_bgr = np.zeros((100, 200, 3), dtype=np.uint8)
        dets = detector.detect(frame_bgr, ["product box"])

        assert len(dets) == 1
        x1, y1, x2, y2 = dets[0]["bbox"]
        assert abs(x1 - 0.25) < 1e-6
        assert abs(y1 - 0.25) < 1e-6
        assert abs(x2 - 0.75) < 1e-6
        assert abs(y2 - 0.75) < 1e-6
        assert dets[0]["confidence"] == 0.9

    def test_empty_queries_returns_empty(self):
        import numpy as np

        from src.overlay_owlv2_adapter import WorkerOwlV2Detector

        detector = WorkerOwlV2Detector(
            processor=MagicMock(), session=MagicMock(), device=MagicMock(),
        )
        assert detector.detect(np.zeros((10, 10, 3), dtype="uint8"), []) == []
