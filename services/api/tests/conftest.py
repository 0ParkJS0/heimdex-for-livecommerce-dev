import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Force-load the full SQLAlchemy model registry before any test configures
# a mapper. Without this, tests that import a single model directly (e.g.
# `from app.modules.search.models import SearchEvent`) trigger Library's
# `LibraryProfile` relationship forward-ref while the profiles module
# hasn't been imported yet, producing:
#   InvalidRequestError: expression 'LibraryProfile' failed to locate a name
import app.db.models  # noqa: F401

from app.modules.tenancy.context import OrgContext


@pytest.fixture
def org_context():
    return OrgContext(org_id=uuid4(), org_slug="testorg")


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    return session


@pytest.fixture
def mock_opensearch_client():
    client = MagicMock()
    client.search_lexical = AsyncMock(return_value=[])
    client.search_vector = AsyncMock(return_value=[])
    client.get_facets = AsyncMock(return_value={"libraries": [], "source_types": [], "people": []})
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_scene_opensearch_client():
    """Mock SceneSearchClient for unit tests."""
    client = MagicMock()
    client.search_lexical = AsyncMock(return_value=[])
    client.search_vector = AsyncMock(return_value=[])
    client.search_visual_vector = AsyncMock(return_value=[])
    client.search_metadata = AsyncMock(return_value=[])
    client.get_facets = AsyncMock(return_value={"libraries": [], "source_types": [], "people": []})
    client.close = AsyncMock()
    return client