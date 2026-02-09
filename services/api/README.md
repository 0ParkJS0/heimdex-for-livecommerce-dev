# Heimdex API

FastAPI backend for the Heimdex video search platform.

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run server
uvicorn app.main:app --reload

# Run tests
pytest

# Lint
ruff check app/
```

## Modules

- `tenancy` - Subdomain → org routing
- `auth` - JWT authentication (dev mode)
- `orgs` - Organization management
- `users` - User management
- `libraries` - Video library management
- `profiles` - Library versioning
- `search` - Hybrid search (BM25 + kNN) with dual-index support (segments + scenes)
- `people` - Face clusters, drive nicknames
- `artifacts` - Asset storage (stub)

## Search Modes

The API supports two search modes controlled by `SEARCH_DEFAULT_MODE`:

| Mode | Value | `POST /api/search` | `POST /api/search/scenes` |
|------|-------|---------------------|---------------------------|
| Segments | `segments` (default) | Segment results | Scene results |
| Scenes | `scenes` | Scene results | Scene results |

Rollback: set `SEARCH_DEFAULT_MODE=segments` and restart.
