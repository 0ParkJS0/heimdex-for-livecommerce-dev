# Heimdex

Video search platform with hybrid lexical + semantic search, supporting Korean language.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- 4GB+ RAM available for containers

### REQUIRED: Add Local DNS Entry

**This step is mandatory.** Heimdex uses strict subdomain-based multi-tenancy.

```bash
# Add to /etc/hosts (requires sudo)
echo "127.0.0.1 devorg.app.heimdex.local" | sudo tee -a /etc/hosts
```

**Why is this required?** See [Multi-Tenancy Architecture](#multi-tenancy-architecture) below.

### Start Everything

```bash
# Start all services (API, Web, Postgres, OpenSearch, MinIO)
docker compose up --build

# Wait for services to be healthy (check with)
docker compose ps

# In a separate terminal, run database migrations and seed data
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
```

### Access the Application

- **Web UI**: http://localhost:3000
- **API Health**: http://devorg.app.heimdex.local:8000/health
- **API Docs**: http://devorg.app.heimdex.local:8000/docs

> **Note**: The API must be accessed via the org subdomain (e.g., `devorg.app.heimdex.local`), 
> not `localhost`. Requests to `localhost:8000` will be rejected by design.

### Test Search

1. Open http://localhost:3000
2. Enter a search query (try Korean: "회의", "프로젝트", "보안")
3. Adjust the alpha slider:
   - **Exact** (alpha=0): Pure keyword matching (BM25)
   - **Balanced** (alpha=0.5): Mix of keyword and semantic
   - **Meaning** (alpha=1): Pure semantic/vector search
4. Enable "Debug Mode" to see ranking scores

### Reset Everything

```bash
docker compose down -v
```

## Architecture

```
heimdex/
├── services/
│   ├── api/          # FastAPI backend (Python 3.11)
│   │   └── app/
│   │       ├── modules/
│   │       │   ├── tenancy/    # Subdomain → org routing
│   │       │   ├── auth/       # Dev JWT auth (OAuth later)
│   │       │   ├── orgs/       # Organization management
│   │       │   ├── users/      # User management
│   │       │   ├── libraries/  # Video libraries
│   │       │   ├── profiles/   # Library versioning
│   │       │   ├── search/     # Hybrid search + fusion
│   │       │   ├── people/     # Face clusters + drive nicknames
│   │       │   └── artifacts/  # Asset storage (stub)
│   │       └── db/
│   │           └── migrations/
│   └── web/          # Next.js frontend (TypeScript)
├── docker-compose.yml
└── docs/
    └── architecture.md
```

### Key Components

- **Tenancy**: Routes `{org}.app.heimdex.local` → org context
- **Search**: Hybrid retrieval (BM25 + kNN) with RRF fusion
- **Diversification**: Limits results per video to prevent dominance

## Multi-Tenancy Architecture

Heimdex uses **strict subdomain-based multi-tenancy**. This is a core security invariant.

### How It Works

```
Browser → http://devorg.app.heimdex.local:8000/api/search
                    ↓
          Host header: devorg.app.heimdex.local
                    ↓
          Tenancy middleware extracts "devorg" from subdomain
                    ↓
          All queries scoped to org_id of "devorg"
```

### Why This Matters

1. **Security**: Organization ID is derived ONLY from the Host header, never from user input.
   This prevents accidental or malicious cross-org data leakage.

2. **Production Parity**: Local development behaves exactly like production.
   No "localhost magic" that could mask tenancy bugs.

3. **Explicit Boundaries**: Every API request clearly identifies its org context.
   No ambiguity about which tenant's data is being accessed.

### Invariants (Never Violate)

| Rule | Rationale |
|------|-----------|
| org_id from Host header ONLY | Prevents client-side manipulation |
| No localhost fallbacks | Keeps dev behavior aligned with prod |
| Reject invalid hosts explicitly | Fail loud, not silent |

### Local Development Setup

The `/etc/hosts` entry maps the org subdomain to localhost:

```
127.0.0.1 devorg.app.heimdex.local
```

The web container uses `extra_hosts: host-gateway` to route API calls through the host machine.

### Verifying Tenancy

Check the `/health` endpoint to see resolved tenancy:

```bash
curl http://devorg.app.heimdex.local:8000/health | jq
```

Response includes:
```json
{
  "status": "ok",
  "tenancy": {
    "host": "devorg.app.heimdex.local:8000",
    "org_slug": "devorg",
    "error": null
  }
}
```

If you see `"error": "localhost"` or `"org_slug": null`, your setup is incorrect.

## API Reference

### Search Endpoint

```bash
POST /api/search
Host: devorg.app.heimdex.local

{
  "q": "search query",
  "alpha": 0.5,
  "filters": {
    "source_types": ["gdrive", "removable_disk"],
    "library_ids": ["uuid"],
    "person_cluster_ids": ["cluster_id"],
    "date_from": "2024-01-01T00:00:00Z",
    "date_to": "2024-12-31T23:59:59Z"
  }
}
```

### Dev Login (Development Only)

```bash
POST /api/auth/dev-login
Host: devorg.app.heimdex.local

{
  "email": "admin@devorg.test"
}
```

Returns JWT token for authenticated endpoints.

## Development

### Run Tests

```bash
# Inside API container
docker compose exec api pytest

# Or locally with dependencies
cd services/api
pip install -e ".[dev]"
pytest
```

### Run Linting

```bash
docker compose exec api ruff check app/
docker compose exec api mypy app/
```

### Database Migrations

```bash
# Create new migration
docker compose exec api alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec api alembic upgrade head

# Rollback
docker compose exec api alembic downgrade -1
```

## Configuration

### Environment Variables (API)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async Postgres connection |
| `OPENSEARCH_URL` | `http://opensearch:9200` | OpenSearch endpoint |
| `JWT_SECRET_KEY` | `dev-secret...` | JWT signing key |
| `EMBEDDING_DIMENSION` | `768` | Vector embedding size |
| `SEARCH_LEXICAL_TOP_K` | `200` | Lexical candidate pool size |
| `SEARCH_VECTOR_TOP_K` | `200` | Vector candidate pool size |
| `SEARCH_RRF_K` | `60` | RRF ranking constant |
| `SEARCH_MAX_SCENES_PER_VIDEO` | `4` | Diversification cap |

## Troubleshooting

### OpenSearch won't start

Increase Docker memory limit or add to `~/.docker/daemon.json`:
```json
{
  "memory": 4096
}
```

### Korean search not working well

The current setup uses a fallback analyzer. For proper Korean support:
1. Install the `analysis-nori` plugin in OpenSearch
2. Update index mappings in `search/client.py`

### Org not found error / Tenancy errors

**Symptom**: API returns 400 with "Multi-tenancy requires org subdomain" or similar.

**Cause**: Missing `/etc/hosts` entry or calling API via `localhost`.

**Fix**:
```bash
# 1. Add hosts entry
echo "127.0.0.1 devorg.app.heimdex.local" | sudo tee -a /etc/hosts

# 2. Verify it works
curl http://devorg.app.heimdex.local:8000/health | jq .tenancy

# Expected: { "org_slug": "devorg", "error": null }
# Wrong:    { "org_slug": null, "error": "localhost" }
```

**Remember**: The API MUST be accessed via the org subdomain, not localhost. This is by design.

## Roadmap

- [ ] Real OAuth integration (Google, SAML)
- [ ] Production embedding model (multilingual-e5-large)
- [ ] Nori analyzer for Korean text
- [ ] Local agent for video playback
- [ ] Cloud GPU worker for heavy compute
- [ ] Real-time indexing pipeline
