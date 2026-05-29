from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.tasks.blur_video import BlurClaimRef, sqs_to_blur_claim
from src.tasks.export_layer import BlurExportRef, sqs_to_export_ref


def _blur_job_body(**overrides) -> dict:
    body = {
        "version": "1",
        "type": "blur.job_created",
        "timestamp": "2026-05-30T00:00:00+00:00",
        "job_id": str(uuid4()),
        "file_id": str(uuid4()),
        "org_id": str(uuid4()),
        "video_id": "gd_video",
        "source_s3_key": "proxies/gd_video/proxy.mp4",
        "source_kind": "proxy",
        "options": {"categories": ["face"]},
    }
    body.update(overrides)
    return body


def _blur_export_body(**overrides) -> dict:
    body = {
        "version": "1",
        "type": "blur.export_created",
        "timestamp": "2026-05-30T00:00:00+00:00",
        "export_id": str(uuid4()),
        "blur_job_id": str(uuid4()),
        "file_id": str(uuid4()),
        "org_id": str(uuid4()),
        "video_id": "gd_video",
        "source_s3_key": "proxies/gd_video/proxy.mp4",
        "mask_s3_keys": {"face": "blurred/gd_video/job/masks/face.mkv"},
        "options": {"categories": ["face"], "format": "prores_4444"},
    }
    body.update(overrides)
    return body


def test_blur_job_adapter_validates_contract_body():
    ref = sqs_to_blur_claim(SimpleNamespace(body=json.dumps(_blur_job_body())))

    assert isinstance(ref, BlurClaimRef)
    assert isinstance(ref.job_id, UUID)
    assert ref.video_id == "gd_video"


def test_blur_job_adapter_rejects_extra_fields():
    body = _blur_job_body(extra_field=True)

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        sqs_to_blur_claim(SimpleNamespace(body=json.dumps(body)))


def test_blur_export_adapter_validates_contract_body():
    ref = sqs_to_export_ref({"Body": json.dumps(_blur_export_body())})

    assert isinstance(ref, BlurExportRef)
    assert isinstance(ref.export_id, UUID)
    assert ref.video_id == "gd_video"


def test_blur_export_adapter_rejects_invalid_category():
    body = _blur_export_body(mask_s3_keys={"bad": "x.mkv"})

    with pytest.raises(ValueError, match="mask_s3_keys"):
        sqs_to_export_ref({"Body": json.dumps(body)})
