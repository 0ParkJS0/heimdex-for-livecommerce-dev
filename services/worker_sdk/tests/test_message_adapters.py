from uuid import UUID, uuid4

import pytest

from heimdex_worker_sdk.internal_api import ClaimedFile, ClaimedProcessingFile
from heimdex_worker_sdk.message_adapters import (
    sqs_to_claimed_file,
    sqs_to_claimed_processing_file,
)
from heimdex_worker_sdk.sqs_client import SQSMessage
from heimdex_worker_sdk.sqs_consumer import InvalidMessageError


@pytest.fixture
def enrichment_message():
    return SQSMessage(
        message_id="msg-enrich-1",
        receipt_handle="receipt-enrich-1",
        body={
            "file_id": str(uuid4()),
            "org_id": str(uuid4()),
            "video_id": "video-abc",
            "keyframe_s3_prefix": "orgs/o/files/f/keyframes/",
            "audio_s3_key": "orgs/o/files/f/audio.wav",
        },
        receive_count=1,
    )


@pytest.fixture
def processing_message():
    return SQSMessage(
        message_id="msg-proc-1",
        receipt_handle="receipt-proc-1",
        body={
            "file_id": str(uuid4()),
            "org_id": str(uuid4()),
            "connection_id": str(uuid4()),
            "google_file_id": "drive-file-123",
            "file_name": "video.mp4",
            "video_id": "video-xyz",
            "mime_type": "video/mp4",
            "file_size_bytes": 12345,
            "library_id": str(uuid4()),
            "scope_type": "drive",
            "drive_id": "drive-1",
        },
        receive_count=1,
    )


class TestSqsToClaimedFile:
    def test_converts_valid_message(self, enrichment_message):
        result = sqs_to_claimed_file(enrichment_message)

        assert isinstance(result, ClaimedFile)
        assert result.id == UUID(enrichment_message.body["file_id"])
        assert result.org_id == UUID(enrichment_message.body["org_id"])
        assert result.video_id == enrichment_message.body["video_id"]
        assert result.keyframe_s3_prefix == enrichment_message.body["keyframe_s3_prefix"]
        assert result.audio_s3_key == enrichment_message.body["audio_s3_key"]
        assert result.lease_token is None

    def test_missing_required_field_raises_invalid_message_error(self, enrichment_message):
        enrichment_message.body.pop("file_id")

        with pytest.raises(InvalidMessageError):
            sqs_to_claimed_file(enrichment_message)

    def test_invalid_uuid_raises_invalid_message_error(self, enrichment_message):
        enrichment_message.body["org_id"] = "not-a-uuid"

        with pytest.raises(InvalidMessageError):
            sqs_to_claimed_file(enrichment_message)


class TestSqsToClaimedProcessingFile:
    def test_converts_valid_message(self, processing_message):
        result = sqs_to_claimed_processing_file(processing_message)

        assert isinstance(result, ClaimedProcessingFile)
        assert result.id == UUID(processing_message.body["file_id"])
        assert result.org_id == UUID(processing_message.body["org_id"])
        assert result.connection_id == UUID(processing_message.body["connection_id"])
        assert result.google_file_id == processing_message.body["google_file_id"]
        assert result.file_name == processing_message.body["file_name"]
        assert result.video_id == processing_message.body["video_id"]
        assert result.mime_type == processing_message.body["mime_type"]
        assert result.file_size_bytes == processing_message.body["file_size_bytes"]
        assert result.library_id == UUID(processing_message.body["library_id"])
        assert result.scope_type == processing_message.body["scope_type"]
        assert result.drive_id == processing_message.body["drive_id"]
        assert result.lease_token is None

    def test_optional_library_id_and_drive_id_are_none_when_missing(self, processing_message):
        processing_message.body["library_id"] = None
        processing_message.body.pop("drive_id")

        result = sqs_to_claimed_processing_file(processing_message)

        assert result.library_id is None
        assert result.drive_id is None
        assert result.lease_token is None

    def test_missing_required_field_raises_invalid_message_error(self, processing_message):
        processing_message.body.pop("google_file_id")

        with pytest.raises(InvalidMessageError):
            sqs_to_claimed_processing_file(processing_message)

    def test_invalid_uuid_raises_invalid_message_error(self, processing_message):
        processing_message.body["connection_id"] = "bad-uuid"

        with pytest.raises(InvalidMessageError):
            sqs_to_claimed_processing_file(processing_message)
