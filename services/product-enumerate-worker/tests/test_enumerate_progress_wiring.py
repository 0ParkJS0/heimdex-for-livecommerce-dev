"""Wiring test for the pipeline progress-callback heartbeat.

Pins the contract that ``handle_enumerate_job`` builds a
``progress_callback`` closure and threads it into BOTH
``enumerate_products`` and ``enumerate_products_overlay``. When the
pipeline invokes the callback with an :class:`EnumerationProgressEvent`,
the worker's ``api.heartbeat`` must be called with:

  * ``stage="enumerating"``
  * ``progress_pct = int(event.progress_pct)``
  * ``progress_label = event.message or event.phase``
  * ``cost_delta_usd = Decimal("0")``
  * ``lease_seconds = settings.worker_lease_seconds``

This is the load-bearing path that fixes the staging "scan orphaned at
pct=30 for 17+ min" failure: without this wiring, the api never sees a
heartbeat between the worker's explicit pct=30 and pct=80 pings, and
the 10-min lease expires every time on a real video.

Pipeline-side throttler + emit point inventory lives in
``heimdex-media-pipelines/tests/product_enum/test_progress.py`` +
``test_pipeline.py`` / ``test_overlay_pipeline.py``. This test only
proves the WORKER side of the bridge.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from heimdex_media_pipelines.product_enum import (
    CanonicalProduct,
    EnumerationProgressEvent,
)
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
    vlm = MagicMock()
    vlm._client = MagicMock()
    vlm.owlv2_processor = MagicMock()
    vlm.owlv2_session = MagicMock()
    vlm.owlv2_device = MagicMock()
    return vlm


def _canonical(label: str) -> CanonicalProduct:
    return CanonicalProduct(
        canonical_scene_id="gd_test_scene_001",
        canonical_frame_idx=10_000,
        canonical_bbox_xywh=(10, 20, 100, 150),
        canonical_crop=Image.new("RGB", (100, 150), (200, 100, 50)),
        llm_label=label,
        siglip2_embedding=[0.1] * 768,
        enumeration_confidence=0.8,
        prominence_score=0.4,
        cluster_size=2,
        rejected_reason=None,
    )


def _message(mode: str = "vision+overlay") -> dict:
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
            frame_idx=10_000,
            image=Image.new("RGB", (640, 480), (128, 128, 128)),
        )
    ]


# Hand-rolled pipeline stubs that invoke ``progress_callback`` exactly
# the way the real pipeline does -- once per phase. Each stub returns
# the SAME (products, cost) shape the real function would.

# Messages are namespaced per pass so the assertion can tell apart
# heartbeats originating from the vision vs. overlay pipeline. Real
# pipeline messages (e.g. "Embedding 1 crops") collide across passes;
# the WORKER doesn't care, but the TEST does -- if we want to assert
# overlay phases didn't leak into vision-only mode, the per-call labels
# need to be distinguishable.
_VISION_PHASES = [
    EnumerationProgressEvent("vision_subsample_done", 32.0, "vision: sampled 1 kf"),
    EnumerationProgressEvent("vision_vlm_batch", 32.0, "vision: VLM batch 1/1"),
    EnumerationProgressEvent("vision_embedding", 60.0, "vision: embedding 1 crops"),
    EnumerationProgressEvent("vision_clustering", 65.0, "vision: clustered 1 groups"),
    EnumerationProgressEvent("vision_done", 68.0, "vision: 1/1 accepted"),
]

_OVERLAY_PHASES = [
    EnumerationProgressEvent("overlay_detector_loop", 68.0, "overlay: scanning 1/1"),
    EnumerationProgressEvent("overlay_extracting", 72.0, "overlay: reading 1/1"),
    EnumerationProgressEvent("overlay_embedding", 77.0, "overlay: embedding 1 crops"),
    EnumerationProgressEvent("overlay_clustering", 78.0, "overlay: clustered 1 groups"),
    EnumerationProgressEvent("overlay_done", 79.0, "overlay: 1/1 accepted"),
]


def _stub_vision_pipeline(*, progress_callback=None, **_):
    """Mimics ``enumerate_products``: replays the documented phase events
    through the supplied callback, returns the canned product list."""
    if progress_callback is not None:
        for ev in _VISION_PHASES:
            progress_callback(ev)
    return ([_canonical("핑크 세럼")], 0.01)


def _stub_overlay_pipeline(*, progress_callback=None, **_):
    """Mimics ``enumerate_products_overlay``: same pattern."""
    if progress_callback is not None:
        for ev in _OVERLAY_PHASES:
            progress_callback(ev)
    return ([_canonical("오버레이 카드 상품")], 0.02)


def _run(message: dict):
    """Drive ``handle_enumerate_job`` end-to-end with the pipeline funcs
    replaced by stubs that invoke ``progress_callback`` for each phase.
    Returns the captured ApiClient mock so tests can assert on
    ``api.heartbeat`` calls."""
    settings = _settings()
    vlm = _vlm_client()
    api = MagicMock()
    api.claim.return_value = {}

    with patch("src.tasks.enumerate.ApiClient", return_value=api), \
        patch("src.tasks.enumerate._fetch_keyframes") as fetch, \
        patch("src.tasks.enumerate.load_siglip", return_value=MagicMock()), \
        patch("src.tasks.enumerate.embed_pil_image_batch", return_value=[[0.1] * 768]), \
        patch("src.tasks.enumerate.enumerate_products", side_effect=_stub_vision_pipeline), \
        patch(
            "src.tasks.enumerate.enumerate_products_overlay",
            side_effect=_stub_overlay_pipeline,
        ), \
        patch("src.tasks.enumerate._upload_crops_and_build_payload", return_value=[]):
        fetch.return_value = (
            _one_keyframe(),
            {"gd_test_scene_001": "29,900 원"},
            None,  # file_name — not exercised in this progress-wiring test
        )
        handle_enumerate_job(message=message, settings=settings, vlm_client=vlm)

    return api


def _heartbeat_phases(api: MagicMock) -> list[str]:
    """Return only the pipeline-emitted heartbeat labels (i.e. the ones
    whose label matches one of our documented phase names). The worker
    also emits 3 explicit milestone heartbeats (pct=10/30/80) with
    human labels like 'Resolving scenes' -- filter those out."""
    documented = {ev.phase for ev in _VISION_PHASES + _OVERLAY_PHASES}
    out = []
    for call in api.heartbeat.call_args_list:
        label = call.kwargs.get("progress_label")
        # The progress_callback emits ``event.message or event.phase`` as
        # the label; we match by either, since the message is the human
        # form and the phase is the routing key.
        for phase in documented:
            if label == phase:
                out.append(phase)
                break
            ev_msg = next(
                (ev.message for ev in _VISION_PHASES + _OVERLAY_PHASES
                 if ev.phase == phase and ev.message == label),
                None,
            )
            if ev_msg is not None:
                out.append(phase)
                break
    return out


# =========================================================================
# vision+overlay — both passes emit, worker bridges every event to api
# =========================================================================

def test_vision_plus_overlay_each_phase_emits_an_api_heartbeat():
    api = _run(_message("vision+overlay"))
    phases_seen = _heartbeat_phases(api)
    # Every documented phase from BOTH passes must show up as a heartbeat.
    expected = {ev.phase for ev in _VISION_PHASES + _OVERLAY_PHASES}
    assert set(phases_seen) >= expected, (
        f"missing pipeline heartbeats: expected {expected}, got {set(phases_seen)}"
    )


def test_heartbeat_payload_shape_matches_api_client_contract():
    """Each pipeline-sourced heartbeat must carry ``stage="enumerating"``
    + ``cost_delta_usd=Decimal("0")`` + lease_seconds from settings.
    Drift here = the api rejects the heartbeat = lease expires anyway."""
    api = _run(_message("vision+overlay"))
    documented_labels = {
        ev.message for ev in _VISION_PHASES + _OVERLAY_PHASES
    } | {ev.phase for ev in _VISION_PHASES + _OVERLAY_PHASES}
    pipeline_calls = [
        c for c in api.heartbeat.call_args_list
        if c.kwargs.get("progress_label") in documented_labels
    ]
    assert pipeline_calls, "no pipeline-emitted heartbeats were captured"
    for call in pipeline_calls:
        assert call.kwargs["stage"] == "enumerating"
        assert call.kwargs["cost_delta_usd"] == Decimal("0")
        assert call.kwargs["lease_seconds"] == _settings().worker_lease_seconds
        # progress_pct is int per the ApiClient signature.
        assert isinstance(call.kwargs["progress_pct"], int)
        assert 0 <= call.kwargs["progress_pct"] <= 100


# =========================================================================
# vision-only — only vision phases bridge
# =========================================================================

def test_vision_only_bridges_only_vision_phases():
    api = _run(_message("vision"))
    phases_seen = _heartbeat_phases(api)
    expected = {ev.phase for ev in _VISION_PHASES}
    assert set(phases_seen) >= expected
    forbidden = {ev.phase for ev in _OVERLAY_PHASES}
    assert not (set(phases_seen) & forbidden), (
        "overlay phase heartbeats leaked into vision-only mode"
    )


# =========================================================================
# overlay-only — only overlay phases bridge
# =========================================================================

def test_overlay_only_bridges_only_overlay_phases():
    api = _run(_message("overlay"))
    phases_seen = _heartbeat_phases(api)
    expected = {ev.phase for ev in _OVERLAY_PHASES}
    assert set(phases_seen) >= expected
    forbidden = {ev.phase for ev in _VISION_PHASES}
    assert not (set(phases_seen) & forbidden), (
        "vision phase heartbeats leaked into overlay-only mode"
    )


# =========================================================================
# broken api.heartbeat must NOT abort enumeration
# =========================================================================

def test_pipeline_heartbeat_failure_does_not_abort_enumeration():
    """``api.heartbeat`` raising from a PIPELINE-bridged event must be
    swallowed by ``_make_progress_cb``. The worker's explicit milestone
    heartbeats (pct=10/30/80) are NOT wrapped -- they remain critical
    boundary calls that the dispatcher converts to ``/fail`` if they
    raise. This test scopes the failure to the bridged calls only."""
    settings = _settings()
    vlm = _vlm_client()
    api = MagicMock()
    api.claim.return_value = {}

    # Fail only when the heartbeat label matches a documented PIPELINE
    # phase or message. Worker milestone labels ("Resolving scenes",
    # "Enumerating (N keyframes)", "Uploading reference crops") flow
    # through unchanged. Without this scoping the test would assert
    # behavior the worker NEVER promised (the pct=30 milestone IS
    # allowed to take down the job).
    pipeline_labels = {ev.message for ev in _VISION_PHASES + _OVERLAY_PHASES}
    pipeline_labels |= {ev.phase for ev in _VISION_PHASES + _OVERLAY_PHASES}

    def _heartbeat(*, progress_label, **kwargs):
        if progress_label in pipeline_labels:
            raise RuntimeError("simulated 503 on pipeline heartbeat")
        return {}

    api.heartbeat.side_effect = _heartbeat

    with patch("src.tasks.enumerate.ApiClient", return_value=api), \
        patch("src.tasks.enumerate._fetch_keyframes") as fetch, \
        patch("src.tasks.enumerate.load_siglip", return_value=MagicMock()), \
        patch("src.tasks.enumerate.embed_pil_image_batch", return_value=[[0.1] * 768]), \
        patch("src.tasks.enumerate.enumerate_products", side_effect=_stub_vision_pipeline), \
        patch(
            "src.tasks.enumerate.enumerate_products_overlay",
            side_effect=_stub_overlay_pipeline,
        ), \
        patch("src.tasks.enumerate._upload_crops_and_build_payload", return_value=[]):
        fetch.return_value = (
            _one_keyframe(),
            {"gd_test_scene_001": "29,900 원"},
            None,  # file_name — not exercised in this progress-wiring test
        )
        # MUST NOT raise even though every PIPELINE-bridged heartbeat
        # raises -- those go through _make_progress_cb's try/except.
        handle_enumerate_job(
            message=_message("vision+overlay"),
            settings=settings,
            vlm_client=vlm,
        )

    # The job completed despite heartbeat storms on the pipeline path.
    assert api.complete_enumeration.call_count == 1
    assert api.fail.call_count == 0
