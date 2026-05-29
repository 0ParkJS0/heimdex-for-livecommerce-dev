from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app import sqs_producer


def _enable_sqs(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.sqs_enabled = True
    monkeypatch.setattr(sqs_producer, "get_settings", lambda: settings)


def test_publish_blur_job_uses_contract_body(monkeypatch: pytest.MonkeyPatch):
    _enable_sqs(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(
        sqs_producer,
        "_publish",
        lambda queue_name, body, dedup_id: captured.update(body=body),
    )

    sqs_producer.publish_blur_job(
        job_id=uuid4(),
        file_id=uuid4(),
        org_id=uuid4(),
        video_id="gd_video",
        proxy_s3_key="proxies/gd_video/proxy.mp4",
        options={"categories": ["face"], "owl_stride": 5},
    )

    assert captured["body"]["type"] == "blur.job_created"
    assert captured["body"]["version"] == "1"
    assert captured["body"]["source_kind"] == "proxy"
    assert captured["body"]["options"]["categories"] == ["face"]


def test_publish_blur_job_rejects_invalid_options(
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_sqs(monkeypatch)
    publish = MagicMock()
    monkeypatch.setattr(sqs_producer, "_publish", publish)

    with pytest.raises(ValueError, match="categories"):
        sqs_producer.publish_blur_job(
            job_id=uuid4(),
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_video",
            proxy_s3_key="proxies/gd_video/proxy.mp4",
            options={"categories": ["not_a_category"]},
        )
    publish.assert_not_called()


def test_publish_blur_export_uses_contract_body(monkeypatch: pytest.MonkeyPatch):
    _enable_sqs(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(
        sqs_producer,
        "_publish",
        lambda queue_name, body, dedup_id: captured.update(body=body),
    )

    sqs_producer.publish_blur_export(
        export_id=uuid4(),
        blur_job_id=uuid4(),
        file_id=uuid4(),
        org_id=uuid4(),
        video_id="gd_video",
        source_s3_key="proxies/gd_video/proxy.mp4",
        mask_s3_keys={"face": "blurred/gd_video/job/masks/face.mkv"},
        categories=["face"],
        export_format="prores_4444",
    )

    assert captured["body"]["type"] == "blur.export_created"
    assert captured["body"]["options"] == {
        "categories": ["face"],
        "format": "prores_4444",
    }


def test_publish_blur_export_rejects_invalid_category(
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_sqs(monkeypatch)
    publish = MagicMock()
    monkeypatch.setattr(sqs_producer, "_publish", publish)

    with pytest.raises(ValueError, match="categories"):
        sqs_producer.publish_blur_export(
            export_id=uuid4(),
            blur_job_id=uuid4(),
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_video",
            source_s3_key="proxies/gd_video/proxy.mp4",
            mask_s3_keys={"face": "blurred/gd_video/job/masks/face.mkv"},
            categories=["bad"],
            export_format="prores_4444",
        )
    publish.assert_not_called()
