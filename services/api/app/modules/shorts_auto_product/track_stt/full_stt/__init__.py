"""Full-STT product explainer submodule.

Replaces the 4-stage storyboard pipeline (mention extraction → chunk
scoring → HOOK/INTRO/DETAIL/CTA slot picker) with a single LLM call over
the complete video transcript. The LLM decides how many segments to pick
and which ones — no prescribed narrative structure.

Public API:
    FullSttExplainerPicker  — the picker (OpenAI call + validation + fallback)
    FullSttClipPlan         — output plan carrying selected segments
    FullSttScene            — one OS scene as input to the picker
    FullSttSegment          — one LLM-selected segment in the output plan
"""

from app.modules.shorts_auto_product.track_stt.full_stt.picker import (
    FullSttExplainerPicker,
)
from app.modules.shorts_auto_product.track_stt.full_stt.serialization import (
    PLAN_SCHEMA_VERSION,
    PlanSchemaVersionError,
    deserialize_plan,
    serialize_plan,
)
from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttScene,
    FullSttSegment,
)

__all__ = [
    "FullSttExplainerPicker",
    "FullSttClipPlan",
    "FullSttScene",
    "FullSttSegment",
    "serialize_plan",
    "deserialize_plan",
    "PLAN_SCHEMA_VERSION",
    "PlanSchemaVersionError",
]
