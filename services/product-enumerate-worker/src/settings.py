"""Settings loader for the product-enumerate-worker.

All env-driven via pydantic-settings, mirroring drive-blur-worker. The
field names with the ``sqs_`` / ``drive_`` prefix come from
:class:`heimdex_worker_sdk.WorkerSettings` so ``build_queue_client``
can resolve them — adding new fields to that base class is the
publish-then-pin protocol per
``feedback_worker_sdk_publish_then_pin``.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- queue + auth (shared with worker-sdk) ----------

    queue_backend: str = "sqs"        # "sqs" | "rabbitmq"
    sqs_consumer_enabled: bool = True
    sqs_region: str = "ap-northeast-2"
    # ``heimdex_worker_sdk.build_queue_client`` reads
    # ``settings.sqs_endpoint_url`` unconditionally (passes ``None``
    # when empty so boto picks the default endpoint). Omitting the
    # field would AttributeError at queue construction.
    sqs_endpoint_url: str = ""

    # ---------- S3 ----------
    # Read keyframes (drive-worker output) + write canonical product
    # crops (this worker's output). Same bucket as the rest of the
    # platform; per-org isolation is path-based (org_id prefix).
    s3_region: str = "ap-northeast-2"
    s3_endpoint_url: str = ""           # MinIO local override; empty in prod
    drive_s3_bucket: str = "heimdex-drive"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # The product enumerate queue (provisioned in AWS during Phase 0).
    sqs_product_enumerate_queue_url: str = ""

    # API base URL + Bearer token for /internal/products/* callbacks.
    drive_api_base_url: str = "http://api:8000"
    drive_internal_api_key: str = ""

    # ---------- worker identity ----------

    worker_id: str = "product-enumerate-worker-local"
    worker_lease_seconds: int = 600
    drive_product_enumerate_concurrency: int = 1

    # ---------- model + LLM ----------

    siglip2_model_id: str = "google/siglip2-base-patch16-256"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_sec: float = 30.0
    openai_max_retries: int = 3
    # Per-keyframe in the new 2-stage pipeline (OWLv2 detects, gpt-4o-mini
    # labels each crop). Keep at 1 — batch>1 has no benefit since OWLv2
    # runs per-frame and per-crop labels are parallelized by
    # ``openai_label_concurrency`` instead.
    openai_batch_size: int = 1
    # Concurrent gpt-4o-mini label-crop calls per keyframe.
    openai_label_concurrency: int = 8

    # ---------- OWLv2 (open-vocab detector, stage 1) ----------

    # ONNX export of OWLv2 — fp32. The transformers/PyTorch checkpoint
    # (google/owlv2-base-patch16-ensemble) was the per-keyframe latency
    # bottleneck, so we switched to the onnx-community export driven via
    # raw onnxruntime-gpu. optimum does not yet support OWLv2 (see
    # huggingface/optimum#1721) so we go one layer below ORTModelForXxx
    # and call onnxruntime.InferenceSession directly.
    owlv2_model_id: str = "onnx-community/owlv2-base-patch16-ensemble-ONNX"
    # Owlv2Processor (text tokenizer + image preprocessor) is pinned to
    # the original google/ repo to keep preprocessing identical to the
    # PyTorch baseline. The onnx-community repo also ships a
    # preprocessor_config.json, but staying on google/ avoids surprise
    # drift from a different processor revision.
    owlv2_processor_id: str = "google/owlv2-base-patch16-ensemble"
    # ONNX file path inside the model repo. fp32 is the safe default;
    # model_fp16.onnx is broken with ORT 1.26's full optimization pass
    # and the quantized variants need threshold recalibration.
    owlv2_onnx_file: str = "onnx/model.onnx"
    # OWLv2's internal post-processor expects square padding; the
    # processor pads to 960x960, so resizing the long edge to 960 avoids
    # wasted compute on letterbox bands.
    owlv2_max_image_side: int = 960
    owlv2_threshold: float = 0.45
    owlv2_nms_iou: float = 0.5
    owlv2_max_dets_per_keyframe: int = 5
    # Padding around each OWLv2 bbox when cropping for the labeling
    # call. Gives gpt-4o-mini a sliver of context to disambiguate
    # 'sweater on hanger' vs 'sweater on model', etc.
    owlv2_crop_pad_frac: float = 0.05

    # ---------- pipeline thresholds ----------

    enumeration_version: str = "v1.0"
    enumeration_prompt_version: str = "v1.0"
    max_keyframes_per_video: int = 60
    enum_prominence_floor_pct: float = 0.03
    enum_cluster_cosine_threshold: float = 0.85
    enum_min_supporting_keyframes: int = 2
    # CALIBRATION (OWLv2 refactor): this floor was tuned for
    # gpt-4o-mini's self-reported confidence (0–1, "I'm confident this
    # is a product"). In the 2-stage pipeline ``EnumerationDetection.
    # confidence`` carries OWLv2's softmax score instead, which sits in
    # ~0.45–0.7 for true positives after ``owlv2_threshold=0.45``.
    # Keeping the floor at 0.6 will reject a wide band of legitimate
    # OWLv2 detections. Re-derive against staging goldens before
    # promoting this branch — likely lower to ~0.45 (redundant with
    # the OWLv2 threshold) or remove the floor entirely.
    enum_min_confidence: float = 0.6

    # Rule-based label-merge is on by default — token-Jaccard (>= 0.6)
    # plus cluster-cosine (>= 0.7) collapses surface-form variants the
    # SigLIP2 clusterer left split ('핑크 세럼' / '분홍 세럼'). The
    # cosine floor keeps brand collisions out (same word, different
    # product). Tighten the env vars if false-merges show up on the
    # consolidation goldens.
    enum_label_merge_enabled: bool = True
    enum_label_merge_token_jaccard: float = 0.6
    enum_label_merge_cosine_floor: float = 0.70
    # LLM-based label-merge is still off by default — it overlaps with
    # the API-side ``CatalogConsolidator`` (gpt-4o) and would double
    # the cost without a precision win on the current golden set.
    enum_label_merge_llm_enabled: bool = False

    # ---------- overlay enumeration (mode=vision+overlay / overlay) ----------
    #
    # Ported from the (now-deleted) in-API
    # ``shorts_auto_product.enumerate_overlay`` config knobs — overlay
    # enumeration is worker-side now. The overlay pass reads on-screen
    # info-overlay graphics (price cards, product callouts) via
    # gpt-4o-mini, crops with the already-loaded OWLv2, embeds with the
    # already-loaded SigLIP2, and clusters with the SAME cosine clusterer
    # the vision path uses. The classical cv2 detector decides which
    # keyframes even carry an overlay before any LLM cost is spent.
    overlay_extraction_model: str = "gpt-4o-mini"
    # Per-UTC-day spend ceiling on the overlay extraction LLM. Crossing
    # it stops further extraction calls; already-extracted candidates
    # still flow through the rest of the pass.
    overlay_extraction_daily_budget_usd: float = 20.0
    # Classical-detector score cutoff: a keyframe must score at or above
    # this to be considered overlay-bearing (gates LLM cost).
    overlay_detector_score_threshold: float = 0.40
    # If a video has product overlays but no indexed OCR text, the
    # classical detector becomes a fragile rectangle-only gate. In that
    # OCR-blind state, let the overlay VLM read the API-sampled keyframes
    # directly instead of returning zero products before model extraction.
    overlay_ocr_blind_fallback_enabled: bool = True
    overlay_ocr_blind_fallback_min_nonempty_ratio: float = 0.10
    # VLM call cap when the overlay pass enters its OCR-blind fallback.
    # The pipelines fallback bypasses the classical detector and sends
    # every keyframe to gpt-4o-mini; the worker sub-samples to this many
    # frames first so extractor cost stays bounded even when
    # max_keyframes_per_video is large.
    overlay_ocr_blind_vlm_cap: int = 60
    # SigLIP2 cluster cosine threshold for the overlay path. Defaults to
    # the vision path's threshold so the same-frame disjointness
    # invariant + consolidate hook behave identically across sources.
    overlay_cluster_cosine_threshold: float = 0.85
    # OCR-grounding filter — drops clusters whose canonical label has no
    # meaningful trigram overlap with the union of scene OCR text. The
    # extractor (gpt-4o-mini) sometimes fabricates labels; OCR is the
    # literal on-screen ground truth. Threshold 0.5 = at least half of
    # the label's character trigrams must appear in OCR somewhere.
    # Disable per-env for incident response or A/B; the filter is
    # post-cluster, so toggling it never changes cluster identity —
    # only the visible / rejected split.
    overlay_ocr_grounding_enabled: bool = True
    overlay_ocr_grounding_threshold: float = 0.5
    # Brand-strip subfilter — removes auto-detected brand tokens from a
    # scoring-only copy of each cluster's canonical label before trigram
    # matching. Catches false positives like 'OSULLOC 라면' where the
    # brand alone carries the trigram score. Disable per-env to fall back
    # to the trigram-only behaviour if brand stripping over-rejects on a
    # specific org.
    overlay_ocr_grounding_brand_strip_enabled: bool = True
    # Brand-token source. ``union`` (default) combines filename-derived
    # brand with OCR-frequency auto-detection so Korean/English brand
    # pairs (e.g. 오설록 + OSULLOC) are both captured.
    # ``filename_only`` / ``auto_only`` / ``filename_then_auto`` are the
    # fallback options for incident response or A/B. Typed as ``Literal``
    # so a typo'd ``.env`` value (e.g. ``unoin``) crashes the worker at
    # boot via pydantic's validation, rather than landing in pipelines'
    # ``ValueError`` mid-job and failing every enumeration message.
    overlay_ocr_grounding_brand_strategy: Literal[
        "filename_only", "auto_only", "union", "filename_then_auto"
    ] = "union"
    # Auto-detect threshold — a token must appear in this share of
    # nonempty scenes to qualify as a brand. 0.30 catches livecommerce
    # brand prefixes (OSULLOC ~98%, 종가 ~75% on the PoC set) without
    # promoting product nouns (참기름 17%, 포기김치 14%).
    overlay_ocr_grounding_brand_min_scene_share: float = 0.30
    # Operational stopword extension for the filename / auto brand
    # detectors. Comma-separated tokens that should NEVER be classified
    # as brand even if they meet the frequency cutoff. Use this to mute
    # an org-specific noise word without a code change. Example:
    # ``굿즈,스페셜키트``.
    overlay_ocr_grounding_brand_filename_stopwords_extra: str = ""
    # VLM prompt OCR-hint gate — appends the scene's PaddleOCR text to
    # the gpt-4o-mini overlay prompt so the model anchors labels against
    # the literal on-screen string. Default True matches the in-PR
    # behaviour the author tested. Flip to False to roll back to the
    # legacy image-only prompt if the hint causes recall loss on a
    # specific corpus; the post-cluster grounding filter
    # (``overlay_ocr_grounding_enabled``) is the independent second
    # rollback lever.
    overlay_extraction_ocr_hint_enabled: bool = True

    # ---------- safety ----------

    product_v2_enabled: bool = False
    enumerate_allow_cpu: bool = False  # block CPU mode unless explicit

    # ---------- observability ----------

    log_level: str = "INFO"
    worker_events_enabled: bool = True
    analytics_enabled: bool = True

    @property
    def use_gpu(self) -> bool:
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False
