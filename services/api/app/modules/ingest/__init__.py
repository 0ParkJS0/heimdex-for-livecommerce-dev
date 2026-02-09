"""
Agent scene ingestion module.

Provides the POST /api/ingest/scenes endpoint that allows the Heimdex agent
to upload scene detection results for indexing into the scenes OpenSearch index.

Auth: Pre-shared API key (Bearer token) + tenancy via Host header.
"""
from app.modules.ingest.auth import verify_agent_token
from app.modules.ingest.router import router as ingest_router

__all__ = ["ingest_router", "verify_agent_token"]
