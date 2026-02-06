# Heimdex Architecture

## Overview

Heimdex is a multi-tenant video search platform that enables scene-level search across video libraries using hybrid lexical + semantic retrieval.

## System Design

```
                                    ┌─────────────────┐
                                    │   Web Browser   │
                                    └────────┬────────┘
                                             │
                              {org}.app.heimdex.local
                                             │
                    ┌────────────────────────┴────────────────────────┐
                    │                                                 │
                    ▼                                                 ▼
           ┌───────────────┐                                 ┌───────────────┐
           │   Web (3000)  │                                 │   API (8000)  │
           │   Next.js     │────────────────────────────────▶│   FastAPI     │
           └───────────────┘                                 └───────┬───────┘
                                                                     │
                    ┌────────────────────────┬────────────────────────┤
                    │                        │                        │
                    ▼                        ▼                        ▼
           ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
           │   Postgres    │        │  OpenSearch   │        │     MinIO     │
           │   (5432)      │        │   (9200)      │        │   (9000)      │
           │               │        │               │        │               │
           │ - orgs        │        │ - segments    │        │ - thumbnails  │
           │ - users       │        │   (kNN+BM25)  │        │ - sprites     │
           │ - libraries   │        │               │        │ - timings     │
           │ - profiles    │        │               │        │               │
           └───────────────┘        └───────────────┘        └───────────────┘
```

## Multi-Tenancy

### Subdomain Routing

Organizations are identified by subdomain:
- `org1.app.heimdex.local` → org_id for "org1"
- `org2.app.heimdex.co` → org_id for "org2"

The `TenancyMiddleware` extracts the org slug from the `Host` header and resolves it to an `org_id` via database lookup. All subsequent queries are scoped to this `org_id`.

### Security Model

- **Server-side enforcement**: `org_id` is NEVER accepted from client input
- **Query scoping**: All database and search queries include `org_id` filter
- **Token validation**: JWT tokens contain `org_id` which is validated against request org

## Search Architecture

### Hybrid Retrieval

```
Query: "프로젝트 회의"
           │
           ▼
    ┌──────┴──────┐
    │             │
    ▼             ▼
┌────────┐  ┌────────────┐
│  BM25  │  │  Embedding │
│ Search │  │   Model    │
└────┬───┘  └─────┬──────┘
     │            │
     ▼            ▼
┌────────┐  ┌────────────┐
│ Top 200│  │  Top 200   │
│Lexical │  │   Vector   │
└────┬───┘  └─────┬──────┘
     │            │
     └──────┬─────┘
            │
            ▼
     ┌──────────────┐
     │ RRF Fusion   │
     │ (alpha=0.5)  │
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │Diversification│
     │(max 4/video) │
     └──────┬───────┘
            │
            ▼
       ┌─────────┐
       │ Top 20  │
       │ Results │
       └─────────┘
```

### RRF Fusion Algorithm

Reciprocal Rank Fusion combines results from multiple retrieval methods:

```python
rrf_score(rank) = 1 / (k + rank)

fused_score = (1 - alpha) * rrf_score(lex_rank) + alpha * rrf_score(vec_rank)
```

Where:
- `k` = 60 (smoothing constant)
- `alpha` = 0..1 (user-controlled weight)
  - `alpha=0`: Pure lexical (BM25)
  - `alpha=1`: Pure semantic (vector)
  - `alpha=0.5`: Balanced hybrid

### Diversification

To prevent a single video from dominating results:
1. Sort candidates by fused_score descending
2. For each candidate:
   - If video has < `max_per_video` scenes in output, include it
   - Otherwise, skip to next candidate
3. If output < target_count, relax constraints

Default: `max_per_video=4`, `target_count=20`

## Data Model

### Relational (Postgres)

```
orgs
├── id (UUID, PK)
├── slug (unique, indexed)
├── name
└── timestamps

users
├── id (UUID, PK)
├── org_id (FK → orgs)
├── email
├── role (admin|member)
└── timestamps

libraries
├── id (UUID, PK)
├── org_id (FK → orgs)
├── name
├── created_by_user_id (FK → users)
└── timestamps

library_profiles
├── id (UUID, PK)
├── org_id (FK → orgs)
├── library_id (FK → libraries)
├── status (building|ready|active|failed)
├── *_version (segmentation, embedding, asr, face)
├── activated_at
└── timestamps

drive_nickname_registry
├── id (UUID, PK)
├── org_id (FK → orgs)
├── source_fingerprint_hash
├── nickname
└── last_seen_at

people_cluster_labels
├── id (UUID, PK)
├── org_id (FK → orgs)
├── person_cluster_id
└── label (nullable)
```

### Search Index (OpenSearch)

```json
{
  "org_id": "keyword",
  "library_id": "keyword",
  "library_profile_id": "keyword",
  "library_name": "keyword",
  "video_id": "keyword",
  "segment_id": "keyword",
  "start_ms": "integer",
  "end_ms": "integer",
  "transcript_raw": "text",
  "transcript_norm": "text (analyzed)",
  "source_type": "keyword",
  "required_drive_nickname": "keyword",
  "people_cluster_ids": "keyword[]",
  "capture_time": "date",
  "embedding_vector": "knn_vector (768-dim)"
}
```

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `tenancy` | Subdomain → org resolution, context injection |
| `auth` | JWT creation/validation, user authentication |
| `orgs` | Organization CRUD |
| `users` | User CRUD (org-scoped) |
| `libraries` | Library CRUD (org-scoped) |
| `profiles` | Library versioning, shadow builds, promotion |
| `search` | Query processing, retrieval, fusion, response formatting |
| `people` | Face cluster labels, drive nickname registry |
| `artifacts` | Asset storage interface (MinIO) |

## Future Considerations

### Korean Language Support

Current implementation uses a fallback analyzer. For production:

1. Install Nori plugin: `bin/opensearch-plugin install analysis-nori`
2. Update index settings:
```json
{
  "analysis": {
    "analyzer": {
      "korean": {
        "type": "nori",
        "decompound_mode": "mixed"
      }
    }
  }
}
```

### Production Embedding Model

Replace mock embeddings with:
- Model: `intfloat/multilingual-e5-large` (768-dim)
- Inference: GPU worker or embedding API service
- Caching: Store embeddings per segment in object storage

### Scaling Considerations

1. **OpenSearch**: Scale horizontally with sharding
2. **Postgres**: Read replicas for search metadata
3. **API**: Stateless, horizontally scalable
4. **Embedding**: GPU worker pool with queue

### Local Agent Architecture (Future)

```
┌─────────────────────────────────────────┐
│              User Machine               │
├─────────────────────────────────────────┤
│  ┌─────────┐    ┌───────────────────┐   │
│  │ Browser │◄──▶│  Localhost Proxy  │   │
│  └─────────┘    │     (Agent)       │   │
│                 └─────────┬─────────┘   │
│                           │             │
│         ┌─────────────────┴──────────┐  │
│         │                            │  │
│         ▼                            ▼  │
│  ┌─────────────┐            ┌──────────┐│
│  │ Local Files │            │  Google  ││
│  │ (USB/HDD)   │            │  Drive   ││
│  └─────────────┘            └──────────┘│
└─────────────────────────────────────────┘
```

The local agent will:
1. Proxy video playback requests
2. Handle removable disk mounting
3. Perform GPU-accelerated processing (optional)
4. Upload sidecars to cloud backend
