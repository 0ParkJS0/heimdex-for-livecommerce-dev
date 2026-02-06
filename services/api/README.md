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
- `search` - Hybrid search (BM25 + kNN)
- `people` - Face clusters, drive nicknames
- `artifacts` - Asset storage (stub)
