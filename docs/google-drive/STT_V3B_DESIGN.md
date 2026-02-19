# V3b Phase 3: STT Enrichment Worker — Design Document

**Date:** 2026-02-19
**Branch:** `refactor/product-scope-alignment`
**Status:** Design (pre-implementation)

## Overview

A new Docker service `drive-stt-worker` that transcribes audio from Google Drive
videos and attaches transcript text to the correct scenes. Users can then search
for videos by what was *said* in them — finding the exact scene without watching
the entire video (Heimdex philosophy).

## Data Flow

```
┌────────────────────────────────────────────────────────────────────┐
│ drive-worker (Phase 1)                                             │
│   original.mp4 ──ffmpeg──> audio.wav ──upload──> S3 audio_s3_key   │
│   scenes ──json──> S3 scene_manifest                               │
│   DB: stt_status="pending", audio_s3_key="org/drive/audio/v/..."   │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ drive-stt-worker (this service)                                    │
│                                                                    │
│  1. Poll DB: claim_stt_pending_files() [SKIP LOCKED]               │
│  2. Download audio.wav from S3 (audio_s3_key)                      │
│  3. Guard: check audio duration ≤ DRIVE_STT_MAX_AUDIO_SECONDS      │
│  4. STT: create_stt_processor() → processor.transcribe(audio.wav)  │
│       └─ Returns: list[TranscriptSegment(start_s, end_s, text)]    │
│  5. Convert: convert_to_speech_segments(segments)                  │
│       └─ Returns: list[SpeechSegment(start, end, text)]            │
│  6. Download scene manifest from S3                                │
│  7. Reconstruct SceneBoundary objects from manifest                │
│  8. Align: assign_segments_to_scenes(boundaries, speech_segments)  │
│       └─ Returns: Dict[scene_id, list[SpeechSegment]]              │
│  9. Aggregate: per-scene transcript_raw + speech_segment_count     │
│ 10. Build updated scenes list (merge into manifest scenes)         │
│ 11. POST /internal/ingest/scenes (re-index with transcripts)       │
│ 12. Update DB: stt_status="done", recompute enrichment_state       │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ SceneIngestService (SaaS API — existing)                           │
│   - normalize_transcript(transcript_raw)                           │
│   - E5 embedding: f"{transcript_norm} {ocr_norm}".strip()          │
│   - Bulk upsert into OpenSearch (doc_id = "{org_id}:{scene_id}")   │
│   - Overwrites existing scene docs (idempotent)                    │
└────────────────────────────────────────────────────────────────────┘
```

## Exact Function Signatures Called

### STT Pipeline (heimdex-media-pipelines)

```python
from heimdex_media_pipelines.speech.stt import (
    create_stt_processor,
    convert_to_speech_segments,
    TranscriptSegment,
)

# Factory — auto-selects backend: faster-whisper → whisper → API
processor = create_stt_processor(
    backend="faster-whisper",   # explicit, no auto-detection surprises
    model_name="small",         # from DRIVE_STT_MODEL
    language="ko",              # from DRIVE_STT_LANGUAGE
    device="cpu",               # workers run on CPU
    compute_type="int8",        # CPU-optimized quantization
    beam_size=1,                # greedy decoding (fast)
    best_of=1,
)

# Transcribe — input: Path to 16kHz mono WAV (already extracted by Phase 1)
segments: list[TranscriptSegment] = processor.transcribe(audio_path)
# TranscriptSegment fields: start_s (float), end_s (float), text (str)

# Convert to SpeechSegment for assign_segments_to_scenes compatibility
from heimdex_media_contracts.speech.schemas import SpeechSegment
speech_segments: list[SpeechSegment] = convert_to_speech_segments(segments)
# SpeechSegment fields: start (float), end (float), text (str), confidence (float)
```

### Segment-to-Scene Alignment (heimdex-media-contracts)

```python
from heimdex_media_contracts.scenes.schemas import SceneBoundary
from heimdex_media_contracts.scenes.merge import (
    assign_segments_to_scenes,
    aggregate_transcript,
)

# Reconstruct SceneBoundary from manifest scene dicts
boundaries = [
    SceneBoundary(
        scene_id=s["scene_id"],
        index=s["index"],
        start_ms=s["start_ms"],
        end_ms=s["end_ms"],
        keyframe_timestamp_ms=s.get("keyframe_timestamp_ms", 0),
    )
    for s in manifest["scenes"]
]

# Assign — maximum temporal overlap algorithm
# Converts SpeechSegment seconds → ms, finds scene with most overlap
assignment: Dict[str, list[SpeechSegment]] = assign_segments_to_scenes(
    scenes=boundaries,
    segments=speech_segments,
)

# Aggregate — concatenate segment texts per scene
for scene_id, assigned in assignment.items():
    transcript_raw: str = aggregate_transcript(assigned)
    speech_segment_count: int = len(assigned)
```

### Internal Ingest (SaaS API — existing)

```python
# POST http://api:8000/internal/ingest/scenes
# Headers:
#   Authorization: Bearer {DRIVE_INTERNAL_API_KEY}
#   X-Heimdex-Org-Id: {org_id}
# Body: IngestScenesRequest JSON
{
    "video_id": "gd_abc123",
    "video_title": "Test Video",
    "library_id": "efe351ac-...",
    "total_duration_ms": 120000,
    "scenes": [
        {
            "scene_id": "gd_abc123_scene_000",
            "index": 0,
            "start_ms": 0,
            "end_ms": 15000,
            "keyframe_timestamp_ms": 7500,
            "transcript_raw": "안녕하세요 이 제품은...",  // ← STT result
            "speech_segment_count": 3,                     // ← STT count
            "ocr_text_raw": "29,900원",                    // preserved from manifest
            "ocr_char_count": 7,                           // preserved
            "source_type": "gdrive"
        }
    ]
}
```

## Alignment Algorithm

### Core: Maximum Temporal Overlap (existing, in contracts)

`assign_segments_to_scenes()` in `heimdex_media_contracts.scenes.merge`:

1. For each speech segment (start_s, end_s in seconds):
   - Convert to milliseconds: `seg_start_ms = int(start_s * 1000)`
   - For each scene boundary (start_ms, end_ms):
     - `overlap = max(0, min(seg_end_ms, scene_end_ms) - max(seg_start_ms, scene_start_ms))`
   - Assign segment to scene with maximum overlap
   - Ties: first scene wins (scenes iterated in order)
2. Within each scene, segments sorted by start time
3. Segments with zero overlap against all scenes: dropped (no assignment)

### Why This Works for Live Commerce

- STT segments from faster-whisper are typically 5–30 seconds (sentence-level)
- Scene boundaries are typically 10–120 seconds (visual cuts)
- Most segments fall entirely within one scene → overlap = full duration
- Segments spanning scene boundaries → assigned to the scene with more overlap
- This is the exact same algorithm used by `assemble_scenes()` in the pipelines
  scene assembler, ensuring consistency between initial ingest and enrichment

### Edge Cases

| Case | Behavior |
|------|----------|
| Segment entirely within scene | Assigned to that scene (full overlap) |
| Segment spans two scenes | Assigned to scene with more overlap |
| Segment before first scene | Dropped (0 overlap) |
| Segment after last scene | Dropped (0 overlap) |
| No speech detected | All scenes get `transcript_raw=""`, `speech_segment_count=0` |
| Scene has no segments | Preserves existing manifest fields (OCR, timing, etc.) |

### Thresholds

- No minimum overlap threshold — any positive overlap counts
- No minimum segment duration — even 0.1s segments are valid
- Transcript truncation: `transcript_raw` max 50,000 chars (enforced by
  `IngestSceneDocument.transcript_raw` Pydantic validation)

## Runtime Guards

| Guard | Config | Default | Behavior |
|-------|--------|---------|----------|
| Feature gate | `DRIVE_STT_ENABLED` | `false` | Container starts, logs "disabled", sleeps |
| Max audio duration | `DRIVE_STT_MAX_AUDIO_SECONDS` | `3600` (1h) | Skip with `stt_status="failed"`, error logged |
| Concurrency | `DRIVE_STT_CONCURRENCY` | `1` | Slot-based (same as OCR worker) |
| Poll interval | `DRIVE_STT_POLL_INTERVAL_SECONDS` | `30` | APScheduler interval trigger |
| Model cache | Volume mount | `/data/whisper-models` | Persists across container restarts |
| Retry limit | Inherited | `max_retries=3` on DriveFile | Worker marks `stt_status="failed"` on exception |

### Duration Guard Implementation

```python
import wave

def _get_audio_duration_seconds(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate if rate > 0 else 0.0
```

Why WAV header, not ffprobe: The audio is already 16kHz mono WAV (extracted by
Phase 1's ffmpeg). Reading the WAV header is instant and avoids an ffprobe
subprocess dependency in the STT worker container.

## Security Boundaries

| Boundary | Enforced |
|----------|----------|
| No OpenSearch access | Worker only talks to Postgres (job claims) and S3 (downloads) |
| Indexing via API only | All scene data goes through `POST /internal/ingest/scenes` |
| Auth: Bearer token | `DRIVE_INTERNAL_API_KEY` on every API call |
| Tenant isolation | `X-Heimdex-Org-Id` header, doc_id = `{org_id}:{scene_id}` |
| No model downloads at runtime | Model cache volume; pre-pull in deployment |
| Read-only mounts | API code mounted `:ro`, contracts/pipelines mounted `:ro` |

## State Machine

### stt_status transitions

```
                  ┌─────────┐
     Phase 1 ──> │ pending │
                  └────┬────┘
                       │ claim_stt_pending_files()
                       ▼
                  ┌─────────┐
                  │ running │
                  └────┬────┘
                  ┌────┴────┐
                  │         │
            success     exception
                  │         │
                  ▼         ▼
            ┌──────┐  ┌────────┐
            │ done │  │ failed │
            └──────┘  └────────┘
```

### enrichment_state derivation (existing `_compute_enrichment_state`)

```
(stt_status, ocr_status) → enrichment_state
───────────────────────────────────────────
(done, done)             → done
(failed, failed)         → failed
(done, failed)           → failed_partial
(failed, done)           → failed_partial
(running, *)             → running
(*, running)             → running
(pending, *)             → pending
(*, pending)             → pending
(None, done)             → done
(None, None)             → pending
```

## Model Selection Rationale

| Model | Size | Korean Quality | CPU Speed (10min audio) | Recommendation |
|-------|------|---------------|------------------------|----------------|
| tiny | 39MB | Poor | ~30s | Not viable for Korean |
| base | 74MB | Mediocre | ~60s | Too many errors |
| small | 244MB | Good | ~3-5min | **Default** — best quality/speed tradeoff |
| medium | 769MB | Very good | ~10-15min | Consider for high-accuracy needs |
| large-v3 | 1.5GB | Excellent | ~20-30min | Too slow for batch processing |

Default: `small` with `compute_type=int8` on CPU. Korean language code: `"ko"`.
Backend: `faster-whisper` (4x faster than openai-whisper, lower memory).

## Fields Updated Per Scene (Re-Ingest)

| Field | Source | Notes |
|-------|--------|-------|
| `transcript_raw` | STT alignment result | Overwritten (was empty from initial ingest) |
| `speech_segment_count` | Count of assigned segments | Overwritten |
| All other fields | Preserved from manifest | OCR, timing, tags, source_type, etc. |

The re-ingest is idempotent: same scene_ids → same doc_ids → OpenSearch overwrites.
Running STT twice produces identical results for the same audio.
