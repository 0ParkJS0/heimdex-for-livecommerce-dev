# PR6 — Scene-First Search

## Current State

The web UI shows **speech segment** results. Each result card displays a segment_id, transcript snippet, timestamps, and a disabled play button. The backend already supports both segment and scene search with identical pipelines.

## Target State

Scenes become the **default unit of retrieval and display**. Each scene card shows: thumbnail, transcript snippet, start/end timestamps, video reference, speech segment count, and a functional play button (when the local agent is reachable).

## API Contract

### Request (unchanged)
```
POST /api/search/scenes
{ "q": "string", "alpha": 0.5, "filters": {} }
```

### Response (SceneSearchResponse)
```json
{
  "results": [{
    "scene_id": "vid123_scene_0",
    "video_id": "vid123",
    "library_id": "uuid",
    "library_name": "My Library",
    "start_ms": 0, "end_ms": 5000,
    "snippet": "transcript text...",
    "thumbnail_url": null,
    "source_type": "gdrive",
    "speech_segment_count": 3,
    "people_cluster_ids": [],
    "debug": { ... }
  }],
  "total_candidates": 100,
  "facets": { ... },
  "query": "search term",
  "alpha": 0.5,
  "result_type": "scene"
}
```

Discriminator: `result_type` field — `"scene"` vs `"segment"`.

## Component Tree Changes

```
SearchContainer
├── SearchBar (unchanged)
├── AlphaSlider (unchanged)
├── FilterPanel (unchanged)
└── SearchResults (updated: union SegmentResult[] | SceneResult[])
    ├── SceneCard (NEW — when result_type=scene)
    │   ├── Thumbnail + rank badge
    │   ├── Library name + source badge
    │   ├── Duration + speech segment count
    │   ├── Snippet
    │   └── PlayButton (enabled when agent available)
    └── ResultCard (existing — when result_type=segment, fallback)
```

## Agent Availability Detection

- `GET http://127.0.0.1:8787/health` — no auth, CORS enabled, 500ms timeout
- If reachable → play button opens `http://127.0.0.1:8787/playback/file?file_id={video_id}`
- If unreachable → play button disabled with "Agent offline" message

## Rollback

Set `NEXT_PUBLIC_SEARCH_MODE=segments` → frontend calls `POST /api/search` instead of `/api/search/scenes`. No code change needed.
