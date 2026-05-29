"""OCR gating contract enforcement at the ingest boundary.

The OCR storage contract lives in heimdex_media_contracts.ocr.gating:
  G2: < 3 chars after strip -> ""
  G3: useful-char ratio < 0.5 -> "" (UI chrome / watermark filter)
  G4: > 10,000 chars -> clamp to 10,000
  ocr_char_count := len(ocr_text_raw_gated)   # raw length, NOT norm length

These tests guard all three SceneIngestService entry points:
  1) ingest_scenes (main video ingest)
  2) enrich_scenes (mixed enrichment)
  3) _enrich_ocr_only_scenes (OCR-only fast path)

A regression here lets ungated OCR slip into OpenSearch and pollutes the
mention_extractor BM25 catalog matching downstream.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.ingest.schemas import EnrichSceneUpdate, EnrichScenesRequest
from app.modules.ingest.service import SceneIngestService, process_ocr_text
from heimdex_media_contracts.ingest import IngestScenesRequest, IngestSceneDocument


def _mock_no_scene_overrides(session: AsyncMock) -> None:
    result = MagicMock()
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)


@pytest.fixture
def mock_scene_client():
    client = MagicMock()
    client.mget_scenes = AsyncMock()
    client.bulk_index_scenes = AsyncMock()
    client.bulk_partial_update_scenes = AsyncMock()
    return client


@pytest.fixture
def service(mock_db_session, mock_scene_client):
    _mock_no_scene_overrides(mock_db_session)
    return SceneIngestService(mock_db_session, mock_scene_client)


def _build_ingest_request(library_id, ocr_text: str) -> IngestScenesRequest:
    return IngestScenesRequest(
        video_id="vid1",
        library_id=library_id,
        scenes=[
            IngestSceneDocument(
                scene_id="vid1_scene_0",
                index=0,
                start_ms=0,
                end_ms=1000,
                ocr_text_raw=ocr_text,
            )
        ],
    )


def _build_enrich_request(ocr_text: str | None) -> EnrichScenesRequest:
    return EnrichScenesRequest(
        video_id="vid1",
        scenes=[EnrichSceneUpdate(scene_id="vid1_scene_0", ocr_text_raw=ocr_text)],
    )


def _patch_library_lookup(service):
    """LibraryRepository.get_by_id is awaited by ingest_scenes."""
    lib = MagicMock()
    return patch(
        "app.modules.ingest.service.LibraryRepository.get_by_id",
        AsyncMock(return_value=lib),
    )


class TestIngestScenesOcrGating:
    """Main ingest path: SceneIngestService.ingest_scenes."""

    @pytest.mark.asyncio
    async def test_short_text_rejected(self, service, mock_scene_client):
        """G2: text under 3 chars stored as empty + char_count=0."""
        org_id = uuid4()
        request = _build_ingest_request(uuid4(), ocr_text="ab")

        with _patch_library_lookup(service), patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[],
        ):
            await service.ingest_scenes(request, org_id)

        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = docs[0]
        assert doc["ocr_text_raw"] == ""
        assert doc["ocr_text_norm"] == ""
        assert doc["ocr_char_count"] == 0

    @pytest.mark.asyncio
    async def test_noise_text_rejected(self, service, mock_scene_client):
        """G3: text with useful-char ratio < 0.5 stored as empty."""
        org_id = uuid4()
        # 9 chars of punctuation, 0 useful -> ratio 0.0 ⇒ noise
        request = _build_ingest_request(uuid4(), ocr_text="!!! @@@ #")

        with _patch_library_lookup(service), patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[],
        ):
            await service.ingest_scenes(request, org_id)

        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = docs[0]
        assert doc["ocr_text_raw"] == ""
        assert doc["ocr_char_count"] == 0

    @pytest.mark.asyncio
    async def test_overlong_text_clamped(self, service, mock_scene_client):
        """G4: text over 10,000 chars clamped to 10,000."""
        org_id = uuid4()
        # IngestSceneDocument schema itself caps at 10,000 (see contracts).
        # Use exactly 10,000 to verify the gate preserves it, not the schema.
        long_text = "가" * 10_000
        request = _build_ingest_request(uuid4(), ocr_text=long_text)

        with _patch_library_lookup(service), patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            await service.ingest_scenes(request, org_id)

        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = docs[0]
        assert len(doc["ocr_text_raw"]) == 10_000
        assert doc["ocr_char_count"] == 10_000

    @pytest.mark.asyncio
    async def test_normal_text_passes_through(self, service, mock_scene_client):
        """Healthy Korean + ASCII text survives gating unchanged."""
        org_id = uuid4()
        request = _build_ingest_request(
            uuid4(),
            ocr_text="라이브커머스 50% 할인",
        )

        with _patch_library_lookup(service), patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            await service.ingest_scenes(request, org_id)

        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = docs[0]
        assert doc["ocr_text_raw"] == "라이브커머스 50% 할인"
        # contracts contract: char_count is len(raw), not len(norm)
        assert doc["ocr_char_count"] == len("라이브커머스 50% 할인")


class TestEnrichScenesOcrGating:
    """Mixed enrichment path: SceneIngestService.enrich_scenes."""

    @pytest.mark.asyncio
    async def test_short_text_rejected(self, service, mock_scene_client):
        """G2 also fires in the mixed enrichment loop."""
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        # Add transcript_raw to keep us off the OCR-only fast path
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[
                EnrichSceneUpdate(
                    scene_id=scene_id,
                    ocr_text_raw="ab",
                    transcript_raw="hello there",
                )
            ],
        )
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {"scene_id": scene_id, "transcript_raw": "", "ocr_text_raw": ""}
        }

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            await service.enrich_scenes(request, org_id)

        _, partial = mock_scene_client.bulk_partial_update_scenes.call_args[0][0][0]
        assert partial["ocr_text_raw"] == ""
        assert partial["ocr_char_count"] == 0


class TestEnrichOcrOnlyGating:
    """Fast path: SceneIngestService._enrich_ocr_only_scenes."""

    @pytest.mark.asyncio
    async def test_noise_text_rejected(self, service, mock_scene_client):
        """OCR-only path must apply the same G3 noise filter."""
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = _build_enrich_request("@@@ !!!")  # pure noise
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {"scene_id": scene_id, "transcript_raw": "", "ocr_text_raw": ""}
        }

        await service.enrich_scenes(request, org_id)

        _, partial = mock_scene_client.bulk_partial_update_scenes.call_args[0][0][0]
        assert partial["ocr_text_raw"] == ""
        assert partial["ocr_char_count"] == 0

    @pytest.mark.asyncio
    async def test_overlong_text_clamped(self, service, mock_scene_client):
        """OCR-only path enforces the 10,000-char cap."""
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = _build_enrich_request("가" * 12_000)
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {"scene_id": scene_id, "transcript_raw": "", "ocr_text_raw": ""}
        }

        await service.enrich_scenes(request, org_id)

        _, partial = mock_scene_client.bulk_partial_update_scenes.call_args[0][0][0]
        assert len(partial["ocr_text_raw"]) == 10_000
        assert partial["ocr_char_count"] == 10_000

    @pytest.mark.asyncio
    async def test_normal_text_passes_through(self, service, mock_scene_client):
        """Healthy text survives the OCR-only path."""
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = _build_enrich_request("라이브커머스 50% 할인")
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {"scene_id": scene_id, "transcript_raw": "", "ocr_text_raw": ""}
        }

        await service.enrich_scenes(request, org_id)

        _, partial = mock_scene_client.bulk_partial_update_scenes.call_args[0][0][0]
        assert partial["ocr_text_raw"] == "라이브커머스 50% 할인"
        assert partial["ocr_char_count"] == len("라이브커머스 50% 할인")


class TestEnrichSchemaCap:
    """The schema accepts raw legacy OCR; service-level gating clamps it."""

    def test_accepts_over_10k_for_service_level_clamp(self):
        update = EnrichSceneUpdate(scene_id="vid1_scene_0", ocr_text_raw="x" * 10_001)
        assert len(update.ocr_text_raw or "") == 10_001

    def test_accepts_exactly_10k(self):
        EnrichSceneUpdate(scene_id="vid1_scene_0", ocr_text_raw="x" * 10_000)


class TestProcessOcrTextHelper:
    """Unit tests for the process_ocr_text() chokepoint."""

    def test_returns_empty_for_none(self):
        assert process_ocr_text(None) == ("", "", 0)

    def test_returns_empty_for_empty_string(self):
        assert process_ocr_text("") == ("", "", 0)

    def test_returns_empty_when_gate_rejects_short_text(self):
        # G2: under 3 chars after strip
        assert process_ocr_text("ab") == ("", "", 0)

    def test_returns_empty_when_gate_rejects_noise(self):
        # G3: pure punctuation — useful-char ratio under 0.5
        assert process_ocr_text("!!! @@@ ###") == ("", "", 0)

    def test_normal_text_returns_consistent_triple(self):
        raw, norm, count = process_ocr_text("라이브커머스 50% 할인")
        assert raw == "라이브커머스 50% 할인"
        # contracts contract: count is len(raw_gated), not len(norm)
        assert count == len(raw)
        assert norm  # normalize_transcript output is non-empty

    def test_clamps_over_10k(self):
        # G4: cap at 10,000 chars
        raw, _, count = process_ocr_text("가" * 12_000)
        assert len(raw) == 10_000
        assert count == 10_000
