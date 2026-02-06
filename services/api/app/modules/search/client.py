from typing import Any

from opensearchpy import AsyncOpenSearch
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_opensearch_client() -> AsyncOpenSearch:
    settings = get_settings()
    return AsyncOpenSearch(
        hosts=[settings.opensearch_url],
        use_ssl=False,
        verify_certs=False,
        ssl_show_warn=False,
    )


class OpenSearchClient:
    EMBEDDING_DIMENSION = 768
    
    def __init__(self):
        self.settings = get_settings()
        self.client = get_opensearch_client()
        self.index_name = f"{self.settings.opensearch_index_prefix}_segments"

    async def close(self):
        await self.client.close()

    async def _check_nori_available(self) -> bool:
        """Check if Nori analyzer plugin is installed in OpenSearch."""
        try:
            response = await self.client.cat.plugins(format="json")
            plugins = [p.get("component", "") for p in response]
            nori_installed = any("analysis-nori" in p for p in plugins)
            logger.info("nori_plugin_check", installed=nori_installed, plugins=plugins)
            return nori_installed
        except Exception as e:
            logger.warning("nori_plugin_check_failed", error=str(e))
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def ensure_index_exists(self) -> None:
        exists = await self.client.indices.exists(index=self.index_name)
        if not exists:
            await self.create_index()

    async def create_index(self) -> None:
        # Check if Nori plugin is available for Korean analysis
        nori_available = await self._check_nori_available()
        
        settings = {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "knn": True,
                "knn.algo_param.ef_search": 100,
            },
            "analysis": {
                "tokenizer": {
                    "korean_tokenizer": {
                        "type": "nori_tokenizer",
                        "decompound_mode": "mixed",  # Keep original + decomposed for better recall
                        "discard_punctuation": False,  # Better for mixed Korean/English
                    },
                } if nori_available else {},
                "filter": {
                    "korean_pos_filter": {
                        "type": "nori_part_of_speech",
                        "stoptags": [
                            "E",   # Verbal endings
                            "IC",  # Interjection
                            "J",   # Ending Particle
                            "MAG", # General Adverb
                            "MAJ", # Conjunctive Adverb
                            "MM",  # Determiner
                            "SP",  # Space
                            "SSC", # Closing brackets
                            "SSO", # Opening brackets
                            "SC",  # Separator
                            "SE",  # Ellipsis
                            "XPN", # Prefix
                            "XSA", # Adjective Suffix
                            "XSN", # Noun Suffix
                            "XSV", # Verb Suffix
                            "UNA", # Unknown
                            "NA",  # Unknown
                            "VSV", # Unknown
                        ],
                    },
                } if nori_available else {},
                "analyzer": {
                    # Korean analyzer using Nori (primary)
                    **({"korean_analyzer": {
                        "type": "custom",
                        "tokenizer": "korean_tokenizer",
                        "filter": ["lowercase", "korean_pos_filter", "nori_readingform"],
                    }} if nori_available else {}),
                    # Fallback analyzer for non-Korean or when Nori unavailable
                    "fallback_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    },
                },
            },
        }
        
        # Use Korean analyzer if available, otherwise fallback
        transcript_analyzer = "korean_analyzer" if nori_available else "fallback_analyzer"
        logger.info(
            "index_analyzer_selected",
            analyzer=transcript_analyzer,
            nori_available=nori_available,
        )
        
        mappings = {
            "properties": {
                "org_id": {"type": "keyword"},
                "library_id": {"type": "keyword"},
                "library_profile_id": {"type": "keyword"},
                "library_name": {"type": "keyword"},
                "video_id": {"type": "keyword"},
                "segment_id": {"type": "keyword"},
                "start_ms": {"type": "integer"},
                "end_ms": {"type": "integer"},
                "transcript_raw": {"type": "text"},
                "transcript_norm": {
                    "type": "text",
                    "analyzer": transcript_analyzer,
                    "search_analyzer": transcript_analyzer,
                },
                # Character length for quality signals (transcript length)
                "transcript_char_count": {"type": "integer"},
                "source_type": {"type": "keyword"},
                "required_drive_nickname": {"type": "keyword"},
                "people_cluster_ids": {"type": "keyword"},
                "capture_time": {"type": "date"},
                "ingest_time": {"type": "date"},
                "thumbnail_url": {"type": "keyword", "index": False},
                "sprite_url": {"type": "keyword", "index": False},
                "word_timing_uri": {"type": "keyword", "index": False},
                "embedding_vector": {
                    "type": "knn_vector",
                    "dimension": self.EMBEDDING_DIMENSION,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": 128, "m": 24},
                    },
                },
            }
        }
        
        logger.info("creating_opensearch_index", index=self.index_name)
        
        try:
            await self.client.indices.create(
                index=self.index_name,
                body={"settings": settings, "mappings": mappings},
            )
            logger.info("opensearch_index_created", index=self.index_name)
        except Exception as e:
            if "resource_already_exists_exception" not in str(e).lower():
                raise
            logger.info("opensearch_index_already_exists", index=self.index_name)

    async def index_segment(self, doc_id: str, document: dict[str, Any]) -> None:
        await self.client.index(
            index=self.index_name,
            id=doc_id,
            body=document,
            refresh=True,
        )

    async def bulk_index(self, documents: list[tuple[str, dict[str, Any]]]) -> None:
        if not documents:
            return
        
        actions = []
        for doc_id, doc in documents:
            actions.append({"index": {"_index": self.index_name, "_id": doc_id}})
            actions.append(doc)
        
        await self.client.bulk(body=actions, refresh=True)
        logger.info("bulk_indexed_documents", count=len(documents))

    async def search_lexical(
        self,
        query: str,
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        """
        BM25 lexical search with phrase boost for short queries.
        
        Short queries (<=3 words) get additional phrase matching boost
        to improve precision for Korean queries like "할인 행사".
        """
        filter_clauses = self._build_filter_clauses(filters)
        
        # Base match query
        match_query = {
            "match": {
                "transcript_norm": {
                    "query": query,
                    "operator": "or",
                    "minimum_should_match": "50%",  # At least half the terms must match
                }
            }
        }
        
        # For short queries, add phrase boost to prioritize exact phrase matches
        # This helps Korean queries like "세일 기간" match "세일 기간입니다" over "세일... 기간"
        query_word_count = len(query.split())
        
        if query_word_count <= 3:
            # Use bool query with phrase boost
            search_query: dict[str, Any] = {
                "bool": {
                    "must": [
                        {"term": {"org_id": org_id}},
                    ],
                    "should": [
                        match_query,
                        {
                            "match_phrase": {
                                "transcript_norm": {
                                    "query": query,
                                    "boost": 2.0,  # Boost exact phrase matches
                                    "slop": 1,    # Allow 1 word between terms
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                    "filter": filter_clauses,
                }
            }
        else:
            # Longer queries use standard match
            search_query = {
                "bool": {
                    "must": [
                        {"term": {"org_id": org_id}},
                        match_query,
                    ],
                    "filter": filter_clauses,
                }
            }
        
        body = {
            "query": search_query,
            "size": size,
            "_source": True,
        }
        
        response = await self.client.search(index=self.index_name, body=body)
        return response["hits"]["hits"]

    async def search_vector(
        self,
        embedding: list[float],
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        filter_clauses = [{"term": {"org_id": org_id}}] + self._build_filter_clauses(filters)
        
        body = {
            "query": {
                "knn": {
                    "embedding_vector": {
                        "vector": embedding,
                        "k": size,
                        "filter": {"bool": {"must": filter_clauses}},
                    }
                }
            },
            "size": size,
            "_source": True,
        }
        
        response = await self.client.search(index=self.index_name, body=body)
        return response["hits"]["hits"]

    async def get_facets(
        self,
        org_id: str,
        filters: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        filter_clauses = [{"term": {"org_id": org_id}}] + self._build_filter_clauses(filters)
        
        body = {
            "query": {"bool": {"filter": filter_clauses}},
            "size": 0,
            "aggs": {
                "libraries": {"terms": {"field": "library_id", "size": 100}},
                "source_types": {"terms": {"field": "source_type", "size": 10}},
                "people": {"terms": {"field": "people_cluster_ids", "size": 100}},
            },
        }
        
        response = await self.client.search(index=self.index_name, body=body)
        
        return {
            "libraries": response["aggregations"]["libraries"]["buckets"],
            "source_types": response["aggregations"]["source_types"]["buckets"],
            "people": response["aggregations"]["people"]["buckets"],
        }

    def _build_filter_clauses(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        clauses: list[dict[str, Any]] = []
        
        if filters.get("date_from") or filters.get("date_to"):
            range_clause: dict[str, Any] = {}
            if filters.get("date_from"):
                range_clause["gte"] = filters["date_from"].isoformat()
            if filters.get("date_to"):
                range_clause["lte"] = filters["date_to"].isoformat()
            clauses.append({"range": {"capture_time": range_clause}})
        
        if filters.get("source_types"):
            clauses.append({"terms": {"source_type": filters["source_types"]}})
        
        if filters.get("library_ids"):
            clauses.append({"terms": {"library_id": [str(lid) for lid in filters["library_ids"]]}})
        
        if filters.get("person_cluster_ids"):
            clauses.append({"terms": {"people_cluster_ids": filters["person_cluster_ids"]}})
        
        return clauses
