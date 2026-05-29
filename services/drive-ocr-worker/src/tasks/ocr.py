import importlib
import json
import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from heimdex_media_pipelines.ocr import process_ocr_blocks
from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "drive-ocr-worker"


def _safe_update_job_status(api_client: Any, video_id: str, file_id: Any, **kwargs: Any) -> None:
    if video_id.startswith("yt_"):
        return
    api_client.update_job_status(file_id, **kwargs)


def select_keyframe_indices(scene_count: int, max_frames: int) -> list[int]:
    if scene_count <= 0 or max_frames <= 0:
        return []
    if scene_count <= max_frames:
        return list(range(scene_count))
    if max_frames == 1:
        return [0]

    indices = {
        round(i * (scene_count - 1) / (max_frames - 1))
        for i in range(max_frames)
    }
    indices.add(0)
    indices.add(scene_count - 1)
    return sorted(indices)[:max_frames]


async def process_ocr_pending_files(api_client: Any, settings: Any, ocr_engine: Any = None) -> None:
    files = api_client.claim_jobs("ocr", limit=1)

    for claimed_file in files:
        _process_single_ocr(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            ocr_engine=ocr_engine,
        )


def _process_single_ocr(
    api_client: Any,
    settings: Any,
    claimed_file: Any,
    ocr_engine: Any = None,
) -> None:
    drive_keys = importlib.import_module("heimdex_worker_sdk.drive_keys")
    scene_manifest_s3_key = drive_keys.scene_manifest_s3_key
    enrichment_keyframe_s3_key = drive_keys.enrichment_keyframe_s3_key
    S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client

    org_id = claimed_file.org_id
    org_id_str = str(org_id)
    file_id = claimed_file.id
    lease_token = claimed_file.lease_token
    video_id = claimed_file.video_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"ocr_{video_id}_"))

    t_start = time.monotonic()

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        manifest_key = scene_manifest_s3_key(org_id_str, video_id)
        manifest_path = temp_dir / "scenes.json"

        try:
            s3.download_file(manifest_key, manifest_path)
        except Exception as e:
            error_msg = f"manifest_download_failed: {type(e).__name__}: {e}"
            _safe_update_job_status(
                api_client, video_id, file_id, job_type="ocr", status="failed", error=error_msg, lease_token=lease_token,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="ocr_failed",
                category="job_failure",
                level="ERROR",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message=error_msg[:1000],
                metadata={
                    "video_id": video_id,
                    "stage": "manifest_download",
                    "error_class": type(e).__name__,
                    "error_msg": str(e)[:500],
                },
            )
            return

        manifest = json.loads(manifest_path.read_text())
        scenes = manifest.get("scenes", [])
        scene_count = len(scenes)

        if scene_count == 0:
            _safe_update_job_status(api_client, video_id, file_id, job_type="ocr", status="done", lease_token=lease_token)
            emit_event(
                service=_SERVICE_NAME,
                event_name="ocr_skipped",
                category="job_failure",
                level="WARNING",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message="no_scenes_in_manifest",
                metadata={
                    "video_id": video_id,
                    "reason": "no_scenes",
                    "error_class": "NoScenes",
                },
            )
            return

        max_frames = min(settings.drive_ocr_max_frames_per_video, scene_count)
        selected_indices = select_keyframe_indices(scene_count, max_frames)

        keyframes_dir = temp_dir / "keyframes"
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        downloaded_keyframes: dict[int, Path] = {}
        for scene_idx in selected_indices:
            scene = scenes[scene_idx]
            scene_id = scene.get("scene_id")
            if not scene_id:
                continue
            s3_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_id)
            local_path = keyframes_dir / f"{scene_id}.jpg"
            try:
                s3.download_file(s3_key, local_path)
                downloaded_keyframes[scene_idx] = local_path
            except Exception:
                logger.warning(
                    "ocr_keyframe_download_failed",
                    extra={"org_id": org_id_str, "video_id": video_id, "scene_id": scene_id, "s3_key": s3_key},
                )

        if not downloaded_keyframes:
            _safe_update_job_status(
                api_client, video_id, file_id, job_type="ocr", status="failed", error="no_keyframes_downloaded", lease_token=lease_token,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="ocr_failed",
                category="job_failure",
                level="ERROR",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message="no_keyframes_downloaded",
                metadata={
                    "video_id": video_id,
                    "stage": "keyframe_download",
                    "error_class": "NoKeyframesDownloaded",
                    "scene_count": scene_count,
                    "selected_count": len(selected_indices),
                },
            )
            return

        ocr_started = time.monotonic()
        if ocr_engine is None:
            try:
                _create = importlib.import_module("heimdex_media_pipelines.ocr").create_ocr_engine
                # ``eager_init=True`` is the default after the
                # heimdex-media-pipelines fix — paddle init / cache
                # permission / version-mismatch failures raise
                # OCREngineInitError here, NOT silently per-frame.
                # See ``ocr-paddle-init-fix.md`` plan + the
                # ``feedback_external_lib_eager_init_fail_loud.md`` memory.
                ocr_engine = _create(lang="korean", use_gpu=settings.use_gpu)
            except Exception as e:
                # Don't mark ocr_status=done. The worker just discovered
                # it can't OCR anything — treat as a worker-level failure
                # so ops sees the unhealthy state via failed status +
                # worker_event. Aircloud's healthcheck will then mark
                # the replica unhealthy on container exit.
                error_msg = f"ocr_engine_init_failed: {type(e).__name__}: {e}"
                logger.exception(
                    "ocr_engine_init_failed",
                    extra={"org_id": org_id_str, "video_id": video_id},
                )
                _safe_update_job_status(
                    api_client, video_id, file_id,
                    job_type="ocr", status="failed",
                    error=error_msg, lease_token=lease_token,
                )
                emit_event(
                    service=_SERVICE_NAME, event_name="ocr_failed",
                    category="job_failure", level="ERROR",
                    org_id=org_id, job_id=file_id,
                    duration_ms=int((time.monotonic() - t_start) * 1000),
                    message=error_msg[:1000],
                    metadata={
                        "video_id": video_id,
                        "stage": "engine_init",
                        "error_class": type(e).__name__,
                        "use_gpu": settings.use_gpu,
                    },
                )
                # Re-raise so the SQS message is NOT ack'd as success.
                # Worker will exit, Aircloud restarts/marks unhealthy.
                raise
        engine = ocr_engine
        ocr_results: dict[int, str] = {}
        ocr_engine_errors = 0  # NEW: per-frame engine-level errors

        for scene_idx, kf_path in downloaded_keyframes.items():
            try:
                blocks = engine.detect(str(kf_path))
            except Exception as exc:
                # ``engine.detect`` swallows per-image data errors and
                # returns []. Anything that bubbles up to here is an
                # engine-level error (paddle runtime bug, etc.). Count
                # them — if EVERY frame errors, that's a worker bug,
                # NOT "video had no text", and we MUST surface it as
                # ocr_failed instead of ocr_completed-with-zeros.
                ocr_engine_errors += 1
                if ocr_engine_errors <= 3:
                    logger.warning(
                        "ocr_engine_per_frame_error",
                        extra={
                            "scene_idx": scene_idx,
                            "kf_path": str(kf_path),
                            "exc_type": type(exc).__name__,
                            "exc_msg": str(exc)[:200],
                        },
                    )
                continue
            postprocessed = process_ocr_blocks(blocks)
            if postprocessed.ocr_text_raw:
                ocr_results[scene_idx] = postprocessed.ocr_text_raw

        # Defense in depth: if EVERY frame errored at the engine level,
        # this is a worker bug (not "video genuinely had no text"). The
        # OCR-Aircloud incident on 2026-05-10 had exactly this
        # signature — 26/26 keyframes raised but ``ocr_status=done``
        # still fired because the empty enrich_scenes path skipped
        # the API POST. Surface as ocr_failed so the success-path event
        # CAN'T fire with zeros across the board.
        if (
            ocr_engine_errors > 0
            and ocr_engine_errors == len(downloaded_keyframes)
        ):
            raise RuntimeError(
                f"OCR engine failed on all {ocr_engine_errors} keyframes "
                f"(video_id={video_id}). Likely engine init or systemic "
                f"GPU failure — check worker logs."
            )

        updated_scenes: list[dict[str, Any]] = []
        total_ocr_chars = 0
        frames_with_text = 0
        for i, scene in enumerate(scenes):
            scene_copy = dict(scene)
            if i in ocr_results:
                ocr_text = ocr_results[i]
                scene_copy["ocr_text_raw"] = ocr_text
                scene_copy["ocr_char_count"] = len(ocr_text)
                total_ocr_chars += len(ocr_text)
                frames_with_text += 1
            updated_scenes.append(scene_copy)

        try:
            ingest_result = _post_enrich_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                scenes=updated_scenes,
            )
        except Exception as e:
            error_msg = f"ocr_reingest_failed: {type(e).__name__}: {e}"
            _safe_update_job_status(
                api_client, video_id, file_id, job_type="ocr", status="failed", error=error_msg, lease_token=lease_token,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="ocr_failed",
                category="job_failure",
                level="ERROR",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message=error_msg[:1000],
                metadata={
                    "video_id": video_id,
                    "stage": "reingest",
                    "error_class": type(e).__name__,
                    "error_msg": str(e)[:500],
                },
            )
            return

        _safe_update_job_status(api_client, video_id, file_id, job_type="ocr", status="done", lease_token=lease_token)

        logger.info(
            "ocr_processing_complete",
            extra={
                "org_id": org_id_str,
                "video_id": video_id,
                "scene_count": scene_count,
                "frames_processed": len(downloaded_keyframes),
                "frames_with_text": frames_with_text,
                "total_ocr_chars": total_ocr_chars,
                "ocr_duration_ms": int((time.monotonic() - ocr_started) * 1000),
                "updated_count": ingest_result.get("updated_count", 0),
            },
        )

        emit_event(
            service=_SERVICE_NAME,
            event_name="ocr_completed",
            category="job_success",
            level="INFO",
            org_id=org_id,
            job_id=file_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            metadata={
                "video_id": video_id,
                "scene_count": scene_count,
                "frames_processed": len(downloaded_keyframes),
                "frames_with_text": frames_with_text,
                "total_ocr_chars": total_ocr_chars,
                # NEW: track per-frame engine errors so partial
                # degradation is visible going forward (the all-frames
                # case raises before reaching here, so this is for
                # detecting "5 of 26 frames errored" patterns).
                "ocr_engine_errors": ocr_engine_errors,
            },
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        _safe_update_job_status(
            api_client, video_id, file_id, job_type="ocr", status="failed", error=error_msg, lease_token=lease_token,
        )
        logger.exception(
            "ocr_processing_failed",
            extra={"org_id": org_id_str, "video_id": video_id},
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="ocr_failed",
            category="job_failure",
            level="ERROR",
            org_id=org_id,
            job_id=file_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            message=error_msg[:1000],
            metadata={
                "video_id": video_id,
                "error_class": type(e).__name__,
                "error_msg": str(e)[:500],
            },
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


ENRICH_BATCH_SIZE = 25


def _post_enrich_to_api(
    settings: Any,
    org_id: Any,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    requests = importlib.import_module("requests")

    enrich_scenes = []
    for scene in scenes:
        if scene.get("ocr_text_raw"):
            enrich_scenes.append(
                {
                    "scene_id": scene["scene_id"],
                    "ocr_text_raw": scene["ocr_text_raw"],
                    "ocr_char_count": scene.get("ocr_char_count", len(scene["ocr_text_raw"])),
                }
            )

    if not enrich_scenes:
        return {"updated_count": 0, "video_id": video_id}

    api_base = settings.drive_api_base_url.rstrip("/")
    url = f"{api_base}/internal/ingest/enrich"
    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "X-Heimdex-Org-Id": str(org_id),
        "Content-Type": "application/json",
    }

    total_updated = 0
    for batch_start in range(0, len(enrich_scenes), ENRICH_BATCH_SIZE):
        batch = enrich_scenes[batch_start : batch_start + ENRICH_BATCH_SIZE]
        payload = {"video_id": video_id, "scenes": batch}

        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Internal enrich API returned {resp.status_code}: {resp.text[:500]}"
            )
        total_updated += resp.json().get("updated_count", 0)

    return {"updated_count": total_updated, "video_id": video_id}
