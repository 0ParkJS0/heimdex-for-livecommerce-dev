import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestTimelineSchemas:

    def test_timeline_scene_model(self):
        from app.modules.people.schemas import PersonTimelineScene

        scene = PersonTimelineScene(
            scene_id="vid1_scene_0",
            start_ms=0,
            end_ms=5000,
            has_person=True,
        )
        assert scene.scene_id == "vid1_scene_0"
        assert scene.start_ms == 0
        assert scene.end_ms == 5000
        assert scene.has_person is True

    def test_timeline_video_model(self):
        from app.modules.people.schemas import (
            PersonTimelineScene,
            PersonTimelineVideo,
        )

        video = PersonTimelineVideo(
            video_id="vid1",
            video_title="Test Video",
            total_scenes=3,
            scenes=[
                PersonTimelineScene(
                    scene_id="vid1_scene_0", start_ms=0, end_ms=5000,
                    has_person=True,
                ),
                PersonTimelineScene(
                    scene_id="vid1_scene_1", start_ms=5000, end_ms=10000,
                    has_person=False,
                ),
                PersonTimelineScene(
                    scene_id="vid1_scene_2", start_ms=10000, end_ms=15000,
                    has_person=True,
                ),
            ],
        )
        assert video.total_scenes == 3
        assert len(video.scenes) == 3
        assert video.scenes[0].has_person is True
        assert video.scenes[1].has_person is False

    def test_timeline_response_model(self):
        from app.modules.people.schemas import PersonTimelineResponse

        resp = PersonTimelineResponse(
            person_cluster_id="cluster_abc",
            videos=[],
        )
        assert resp.person_cluster_id == "cluster_abc"
        assert resp.videos == []

    def test_timeline_video_title_defaults_to_none(self):
        from app.modules.people.schemas import PersonTimelineVideo

        video = PersonTimelineVideo(
            video_id="vid1",
            total_scenes=0,
            scenes=[],
        )
        assert video.video_title is None


# ---------------------------------------------------------------------------
# OpenSearch get_person_timeline
# ---------------------------------------------------------------------------
class TestGetPersonTimeline:

    @pytest.fixture
    def mock_scene_client(self):
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client"):

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test_scenes"
            settings.opensearch_bulk_refresh = "true"
            settings.ocr_search_enabled = True
            settings.ocr_bm25_boost = 0.6
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    @pytest.mark.asyncio
    async def test_empty_when_no_videos(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {"video_ids": {"buckets": []}},
        })

        result = await client.get_person_timeline("org_1", "cluster_x")

        assert result == []
        async_client.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_two_queries_issued(self, mock_scene_client):
        client, async_client = mock_scene_client

        resp_video_ids = {
            "aggregations": {
                "video_ids": {
                    "buckets": [{"key": "vid_a"}, {"key": "vid_b"}],
                },
            },
        }
        resp_all_scenes = {
            "aggregations": {
                "by_video": {
                    "buckets": [],
                },
            },
        }
        async_client.search = AsyncMock(
            side_effect=[resp_video_ids, resp_all_scenes],
        )

        await client.get_person_timeline("org_1", "cluster_x")

        assert async_client.search.call_count == 2

    @pytest.mark.asyncio
    async def test_query1_filters_by_person(self, mock_scene_client):
        client, async_client = mock_scene_client

        async_client.search = AsyncMock(return_value={
            "aggregations": {"video_ids": {"buckets": []}},
        })

        await client.get_person_timeline("org_42", "cluster_abc")

        call_args = async_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        filters = body["query"]["bool"]["filter"]
        assert {"term": {"org_id": "org_42"}} in filters
        assert {"term": {"people_cluster_ids": "cluster_abc"}} in filters

    @pytest.mark.asyncio
    async def test_query2_uses_video_ids_from_query1(self, mock_scene_client):
        client, async_client = mock_scene_client

        resp_video_ids = {
            "aggregations": {
                "video_ids": {
                    "buckets": [{"key": "vid_a"}, {"key": "vid_b"}],
                },
            },
        }
        resp_all_scenes = {
            "aggregations": {"by_video": {"buckets": []}},
        }
        async_client.search = AsyncMock(
            side_effect=[resp_video_ids, resp_all_scenes],
        )

        await client.get_person_timeline("org_1", "cluster_x")

        second_call = async_client.search.call_args_list[1]
        body = second_call.kwargs.get("body") or second_call[1].get("body")
        filters = body["query"]["bool"]["filter"]
        terms_filter = next(f for f in filters if "terms" in f)
        assert set(terms_filter["terms"]["video_id"]) == {"vid_a", "vid_b"}

    @pytest.mark.asyncio
    async def test_has_person_flag_accuracy(self, mock_scene_client):
        client, async_client = mock_scene_client

        target_cluster = "cluster_target"

        resp_video_ids = {
            "aggregations": {
                "video_ids": {"buckets": [{"key": "vid_1"}]},
            },
        }
        resp_all_scenes = {
            "aggregations": {
                "by_video": {
                    "buckets": [{
                        "key": "vid_1",
                        "video_title": {"buckets": [{"key": "Test Video"}]},
                        "scenes": {
                            "hits": {
                                "hits": [
                                    {
                                        "_source": {
                                            "scene_id": "vid_1_scene_0",
                                            "start_ms": 0,
                                            "end_ms": 5000,
                                            "people_cluster_ids": [
                                                target_cluster, "other",
                                            ],
                                        },
                                    },
                                    {
                                        "_source": {
                                            "scene_id": "vid_1_scene_1",
                                            "start_ms": 5000,
                                            "end_ms": 10000,
                                            "people_cluster_ids": ["other"],
                                        },
                                    },
                                    {
                                        "_source": {
                                            "scene_id": "vid_1_scene_2",
                                            "start_ms": 10000,
                                            "end_ms": 15000,
                                            "people_cluster_ids": [],
                                        },
                                    },
                                    {
                                        "_source": {
                                            "scene_id": "vid_1_scene_3",
                                            "start_ms": 15000,
                                            "end_ms": 20000,
                                            "people_cluster_ids": [
                                                target_cluster,
                                            ],
                                        },
                                    },
                                ],
                            },
                        },
                    }],
                },
            },
        }

        async_client.search = AsyncMock(
            side_effect=[resp_video_ids, resp_all_scenes],
        )

        result = await client.get_person_timeline("org_1", target_cluster)

        assert len(result) == 1
        video = result[0]
        assert video["video_id"] == "vid_1"
        assert video["video_title"] == "Test Video"
        assert video["total_scenes"] == 4

        scenes = video["scenes"]
        assert scenes[0]["has_person"] is True
        assert scenes[1]["has_person"] is False
        assert scenes[2]["has_person"] is False
        assert scenes[3]["has_person"] is True

    @pytest.mark.asyncio
    async def test_scenes_sorted_by_start_ms(self, mock_scene_client):
        client, async_client = mock_scene_client

        resp_video_ids = {
            "aggregations": {
                "video_ids": {"buckets": [{"key": "vid_1"}]},
            },
        }
        resp_all_scenes = {
            "aggregations": {
                "by_video": {
                    "buckets": [{
                        "key": "vid_1",
                        "video_title": {"buckets": []},
                        "scenes": {
                            "hits": {
                                "hits": [
                                    {
                                        "_source": {
                                            "scene_id": "s0",
                                            "start_ms": 0,
                                            "end_ms": 3000,
                                            "people_cluster_ids": ["c1"],
                                        },
                                    },
                                    {
                                        "_source": {
                                            "scene_id": "s1",
                                            "start_ms": 3000,
                                            "end_ms": 6000,
                                            "people_cluster_ids": [],
                                        },
                                    },
                                ],
                            },
                        },
                    }],
                },
            },
        }
        async_client.search = AsyncMock(
            side_effect=[resp_video_ids, resp_all_scenes],
        )

        result = await client.get_person_timeline("org_1", "c1")

        scenes = result[0]["scenes"]
        assert scenes[0]["start_ms"] < scenes[1]["start_ms"]

    @pytest.mark.asyncio
    async def test_query2_sort_specifies_start_ms_asc(self, mock_scene_client):
        client, async_client = mock_scene_client

        resp_video_ids = {
            "aggregations": {
                "video_ids": {"buckets": [{"key": "v1"}]},
            },
        }
        resp_all_scenes = {
            "aggregations": {"by_video": {"buckets": []}},
        }
        async_client.search = AsyncMock(
            side_effect=[resp_video_ids, resp_all_scenes],
        )

        await client.get_person_timeline("org_1", "c1")

        second_call = async_client.search.call_args_list[1]
        body = second_call.kwargs.get("body") or second_call[1].get("body")
        top_hits = body["aggs"]["by_video"]["aggs"]["scenes"]["top_hits"]
        assert top_hits["sort"] == [{"start_ms": "asc"}]

    @pytest.mark.asyncio
    async def test_handles_null_people_cluster_ids(self, mock_scene_client):
        client, async_client = mock_scene_client

        resp_video_ids = {
            "aggregations": {
                "video_ids": {"buckets": [{"key": "vid_1"}]},
            },
        }
        resp_all_scenes = {
            "aggregations": {
                "by_video": {
                    "buckets": [{
                        "key": "vid_1",
                        "video_title": {"buckets": [{"key": "Video"}]},
                        "scenes": {
                            "hits": {
                                "hits": [
                                    {
                                        "_source": {
                                            "scene_id": "s0",
                                            "start_ms": 0,
                                            "end_ms": 5000,
                                            "people_cluster_ids": None,
                                        },
                                    },
                                    {
                                        "_source": {
                                            "scene_id": "s1",
                                            "start_ms": 5000,
                                            "end_ms": 10000,
                                        },
                                    },
                                ],
                            },
                        },
                    }],
                },
            },
        }
        async_client.search = AsyncMock(
            side_effect=[resp_video_ids, resp_all_scenes],
        )

        result = await client.get_person_timeline("org_1", "cluster_x")

        scenes = result[0]["scenes"]
        assert scenes[0]["has_person"] is False
        assert scenes[1]["has_person"] is False

    @pytest.mark.asyncio
    async def test_multiple_videos_returned(self, mock_scene_client):
        client, async_client = mock_scene_client

        resp_video_ids = {
            "aggregations": {
                "video_ids": {
                    "buckets": [{"key": "vid_a"}, {"key": "vid_b"}],
                },
            },
        }
        resp_all_scenes = {
            "aggregations": {
                "by_video": {
                    "buckets": [
                        {
                            "key": "vid_a",
                            "video_title": {
                                "buckets": [{"key": "Video A"}],
                            },
                            "scenes": {
                                "hits": {
                                    "hits": [{
                                        "_source": {
                                            "scene_id": "va_s0",
                                            "start_ms": 0,
                                            "end_ms": 5000,
                                            "people_cluster_ids": ["c1"],
                                        },
                                    }],
                                },
                            },
                        },
                        {
                            "key": "vid_b",
                            "video_title": {
                                "buckets": [{"key": "Video B"}],
                            },
                            "scenes": {
                                "hits": {
                                    "hits": [{
                                        "_source": {
                                            "scene_id": "vb_s0",
                                            "start_ms": 0,
                                            "end_ms": 3000,
                                            "people_cluster_ids": [],
                                        },
                                    }],
                                },
                            },
                        },
                    ],
                },
            },
        }
        async_client.search = AsyncMock(
            side_effect=[resp_video_ids, resp_all_scenes],
        )

        result = await client.get_person_timeline("org_1", "c1")

        assert len(result) == 2
        video_ids = {v["video_id"] for v in result}
        assert video_ids == {"vid_a", "vid_b"}
