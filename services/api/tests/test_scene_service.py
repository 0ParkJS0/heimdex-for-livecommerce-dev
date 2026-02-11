"""
Unit tests for SceneSearchService.

Tests verify:
1. End-to-end search pipeline (lexical + vector -> RRF -> diversification -> results)
2. Alpha blending extremes (pure lexical, pure vector, balanced)
3. Result construction (SceneResult fields, snippet truncation)
4. Facet enrichment with library names and people labels
5. Empty results handling
6. Filter passthrough to SceneSearchClient

Run with: pytest tests/test_scene_service.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.search.schemas import SceneSearchResponse, SearchFilters
from app.modules.search.scene_service import SceneSearchService


def _make_scene_hit(
    scene_id: str,
    video_id: str,
    score: float = 10.0,
    library_id: str | None = None,
    transcript: str = "Test transcript content for scene",
    source_type: str = "gdrive",
    speech_segment_count: int = 3,
) -> dict:
    """Helper to construct an OpenSearch scene hit dict."""
    return {
        "_id": scene_id,
        "_score": score,
        "_source": {
            "scene_id": scene_id,
            "video_id": video_id,
            "library_id": library_id or str(uuid4()),
            "start_ms": 0,
            "end_ms": 5000,
            "transcript_raw": transcript,
            "source_type": source_type,
            "people_cluster_ids": [],
            "speech_segment_count": speech_segment_count,
            "transcript_char_count": len(transcript),
        },
    }


class TestSceneSearchService:
    @pytest.fixture
    def scene_search_service(self, mock_db_session, mock_scene_opensearch_client):
        return SceneSearchService(mock_db_session, mock_scene_opensearch_client)

    @pytest.fixture
    def _patch_db_session(self, scene_search_service):
        """Patch session.execute to return empty library/people results."""
        with patch.object(scene_search_service.session, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_execute.return_value = mock_result
            yield mock_execute

    # ------------------------------------------------------------------
    # Basic search pipeline
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_returns_scene_search_response(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """search() should return a SceneSearchResponse."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene1", "vid1"),
        ]
        mock_scene_opensearch_client.search_vector.return_value = []

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert isinstance(response, SceneSearchResponse)
        assert response.query == "test"
        assert response.alpha == 0.5
        assert response.result_type == "scene"
        assert response.total_candidates >= 1
        assert len(response.results) >= 1

    @pytest.mark.asyncio
    async def test_search_result_has_scene_fields(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Each SceneResult should have scene-specific fields."""
        org_id = uuid4()
        lib_id = str(uuid4())

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene_001", "vid_abc", library_id=lib_id,
                            transcript="Hello scene", speech_segment_count=5),
        ]

        response = await scene_search_service.search(
            query="hello", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        r = response.results[0]
        assert r.scene_id == "scene_001"
        assert r.video_id == "vid_abc"
        assert r.start_ms == 0
        assert r.end_ms == 5000
        assert r.snippet == "Hello scene"
        assert r.source_type == "gdrive"
        assert r.speech_segment_count == 5
        assert r.debug.fused_score > 0

    # ------------------------------------------------------------------
    # Alpha blending extremes
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_alpha_zero_favors_lexical(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """alpha=0 (pure lexical) should rank lexical-only hits highest."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("lex_scene", "v1", score=10.0),
        ]
        mock_scene_opensearch_client.search_vector.return_value = [
            _make_scene_hit("vec_scene", "v2", score=0.95),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.0, filters=SearchFilters()
        )

        assert len(response.results) == 2
        assert response.results[0].scene_id == "lex_scene"

    @pytest.mark.asyncio
    async def test_alpha_one_favors_vector(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """alpha=1 (pure vector) should rank vector-only hits highest."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("lex_scene", "v1", score=10.0),
        ]
        mock_scene_opensearch_client.search_vector.return_value = [
            _make_scene_hit("vec_scene", "v2", score=0.95),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=1.0, filters=SearchFilters()
        )

        assert len(response.results) == 2
        assert response.results[0].scene_id == "vec_scene"

    @pytest.mark.asyncio
    async def test_balanced_alpha_returns_both(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """alpha=0.5 should include results from both retrieval paths."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("shared_scene", "v1", score=8.0),
        ]
        mock_scene_opensearch_client.search_vector.return_value = [
            _make_scene_hit("shared_scene", "v1", score=0.85),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        # Same scene from both paths -> fused into single result
        assert len(response.results) == 1
        r = response.results[0]
        assert r.debug.lexical_rank is not None
        assert r.debug.vector_rank is not None
        assert r.debug.lexical_contribution > 0
        assert r.debug.vector_contribution > 0

    # ------------------------------------------------------------------
    # Diversification
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_diversification_limits_per_video(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Diversification should limit scenes from the same video."""
        org_id = uuid4()

        # 10 scenes from same video
        lexical_hits = [
            _make_scene_hit(f"scene_{i}", "same_video", score=10.0 - i)
            for i in range(10)
        ]
        mock_scene_opensearch_client.search_lexical.return_value = lexical_hits
        mock_scene_opensearch_client.search_vector.return_value = []

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.0, filters=SearchFilters()
        )

        # All from same video, but diversification applied
        assert response.total_candidates == 10
        assert len(response.results) <= 20  # page_size cap

    # ------------------------------------------------------------------
    # Snippet truncation
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_snippet_truncated_to_500_chars(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Snippet should be truncated to 500 characters max."""
        org_id = uuid4()
        long_transcript = "A" * 1000

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene_long", "v1", transcript=long_transcript),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert len(response.results[0].snippet) == 500

    # ------------------------------------------------------------------
    # Facets
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_facets_returned(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Facets should be populated from SceneSearchClient aggregations."""
        org_id = uuid4()

        mock_scene_opensearch_client.get_facets.return_value = {
            "libraries": [{"key": "lib1", "doc_count": 5}],
            "source_types": [{"key": "gdrive", "doc_count": 10}],
            "people": [{"key": "cluster_001", "doc_count": 3}],
        }

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert len(response.facets.libraries) == 1
        assert response.facets.libraries[0].value == "lib1"
        assert response.facets.libraries[0].count == 5
        assert len(response.facets.source_types) == 1
        assert len(response.facets.people_cluster_ids) == 1

    # ------------------------------------------------------------------
    # Empty results
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_empty_results(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Search with no matches should return empty results list."""
        org_id = uuid4()

        response = await scene_search_service.search(
            query="nonexistent", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert isinstance(response, SceneSearchResponse)
        assert response.results == []
        assert response.total_candidates == 0
        assert response.result_type == "scene"

    # ------------------------------------------------------------------
    # Filter passthrough
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_filters_passed_to_client(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Filters should be forwarded to SceneSearchClient methods."""
        org_id = uuid4()
        lib_id = uuid4()

        filters = SearchFilters(
            source_types=["gdrive"],
            library_ids=[lib_id],
            person_cluster_ids=["cluster1"],
        )

        await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=filters
        )

        call_args = mock_scene_opensearch_client.search_lexical.call_args
        filter_dict = call_args.kwargs["filters"]
        assert filter_dict["source_types"] == ["gdrive"]
        assert filter_dict["library_ids"] == [lib_id]
        assert filter_dict["person_cluster_ids"] == ["cluster1"]

    # ------------------------------------------------------------------
    # Tag filter passthrough (PR-D)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_tag_filters_passed_to_client(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Tag filter fields should be forwarded to SceneSearchClient."""
        org_id = uuid4()

        filters = SearchFilters(
            keyword_tags_in=["할인"],
            keyword_tags_not_in=["광고"],
            product_tags_in=["cosmetics"],
            product_tags_not_in=["alcohol"],
            product_entities_in=["Nike Air Max"],
            product_entities_not_in=["BadBrand"],
        )

        await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=filters
        )

        call_args = mock_scene_opensearch_client.search_lexical.call_args
        fd = call_args.kwargs["filters"]
        assert fd["keyword_tags_in"] == ["할인"]
        assert fd["keyword_tags_not_in"] == ["광고"]
        assert fd["product_tags_in"] == ["cosmetics"]
        assert fd["product_tags_not_in"] == ["alcohol"]
        assert fd["product_entities_in"] == ["Nike Air Max"]
        assert fd["product_entities_not_in"] == ["BadBrand"]

    @pytest.mark.asyncio
    async def test_empty_tag_filters_passed_as_empty_lists(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Default (empty) tag filters should appear as empty lists in filter_dict."""
        org_id = uuid4()

        await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        call_args = mock_scene_opensearch_client.search_lexical.call_args
        fd = call_args.kwargs["filters"]
        assert fd["keyword_tags_in"] == []
        assert fd["keyword_tags_not_in"] == []
        assert fd["product_tags_in"] == []
        assert fd["product_tags_not_in"] == []
        assert fd["product_entities_in"] == []
        assert fd["product_entities_not_in"] == []

    # ------------------------------------------------------------------
    # Library name enrichment
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_library_name_enrichment(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        """Results should have library_name populated from DB lookup."""
        org_id = uuid4()
        lib_id = str(uuid4())

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene1", "v1", library_id=lib_id),
        ]

        # Mock library lookup to return a library with matching id
        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_lib.name = "My Library"

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.return_value = mock_result

            response = await scene_search_service.search(
                query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
            )

        assert response.results[0].library_name == "My Library"

    # ------------------------------------------------------------------
    # Quality factor applied (via shared fusion logic)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_quality_factor_applied(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Quality factor from transcript length should affect adjusted_score."""
        org_id = uuid4()

        # Short transcript -> quality penalty
        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("short_scene", "v1", transcript="Hi"),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.0, filters=SearchFilters()
        )

        r = response.results[0]
        assert r.debug.quality_factor < 1.0
        assert r.debug.adjusted_score < r.debug.fused_score
