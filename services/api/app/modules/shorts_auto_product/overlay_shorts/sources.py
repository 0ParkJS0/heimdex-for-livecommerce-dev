"""Default adapters for the shorts-assembler's source protocols.

* :class:`OpenSearchSceneSttLoader` -- pulls one ``SttSegment`` per
  scene from the ``scenes`` index, using ``start_ms`` / ``end_ms``
  and ``transcript_raw``. Word-level transcript is not yet generally
  available; the assembler's keyword search and silence-snapping work
  well enough at scene granularity.
* :class:`FfmpegSilenceLoader` -- invokes ``ffmpeg -af silencedetect``
  on a local copy of the source video and parses the stderr output.
  A caller-supplied ``video_path_resolver`` maps ``video_drive_id`` to
  a filesystem path, so this module never has to know about S3 or
  drive_files.

Both classes implement the :class:`SttLoader` / :class:`SilenceLoader`
protocols defined in :mod:`.service`. Tests can pass any duck-typed
substitute.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.modules.shorts_auto_product.overlay_shorts.errors import (
    OverlayShortsSourceUnavailableError,
)
from app.modules.shorts_auto_product.overlay_shorts.service import (
    SttSegment,
)

logger = logging.getLogger(__name__)


_MAX_SCENES_PER_QUERY = 5000


class OpenSearchSceneSttLoader:
    """SttLoader backed by the ``scenes`` OpenSearch index.

    Returns one :class:`SttSegment` per scene whose ``transcript_raw``
    is non-empty. ``start_s`` / ``end_s`` come from the scene's
    ``start_ms`` / ``end_ms``.
    """

    def __init__(
        self,
        *,
        os_client: Any,
        index_alias: str,
        org_id: UUID,
    ) -> None:
        self._os_client = os_client
        self._index_alias = index_alias
        self._org_id = org_id

    async def get_for_video(self, video_drive_id: str) -> list[SttSegment]:
        response = await self._os_client.search(
            index=self._index_alias,
            body={
                "size": _MAX_SCENES_PER_QUERY,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"org_id": str(self._org_id)}},
                            {"term": {"video_id": video_drive_id}},
                        ],
                    },
                },
                "_source": ["start_ms", "end_ms", "transcript_raw"],
                "sort": [{"start_ms": "asc"}],
            },
        )
        hits = response.get("hits", {}).get("hits", []) or []
        out: list[SttSegment] = []
        for hit in hits:
            src = hit.get("_source", {}) or {}
            text = (src.get("transcript_raw") or "").strip()
            if not text:
                continue
            start_ms = src.get("start_ms")
            end_ms = src.get("end_ms")
            if start_ms is None or end_ms is None:
                continue
            out.append(
                SttSegment(
                    start_s=float(start_ms) / 1000.0,
                    end_s=float(end_ms) / 1000.0,
                    text=text,
                )
            )
        return out


# Defaults match the workspace prototype.
_SILENCE_DB_DEFAULT = -28
_SILENCE_MIN_DUR_DEFAULT = 0.18


class FfmpegSilenceLoader:
    """SilenceLoader that calls ``ffmpeg -af silencedetect``.

    The video must be on the local filesystem -- the caller supplies a
    ``video_path_resolver`` that maps ``video_drive_id`` to a
    :class:`Path`. A small per-video cache lives next to the source
    (``<name>.silence.json``) so a re-run does not re-scan.
    """

    def __init__(
        self,
        *,
        video_path_resolver: Callable[[str], Awaitable[Path | None]],
        silence_db: int = _SILENCE_DB_DEFAULT,
        silence_min_dur_s: float = _SILENCE_MIN_DUR_DEFAULT,
    ) -> None:
        self._resolver = video_path_resolver
        self._silence_db = silence_db
        self._silence_min_dur_s = silence_min_dur_s

    async def get_for_video(
        self, video_drive_id: str
    ) -> list[tuple[float, float]]:
        path = await self._resolver(video_drive_id)
        if path is None or not path.is_file():
            raise OverlayShortsSourceUnavailableError(
                f"silence loader: video {video_drive_id} not on disk"
            )
        cache = path.with_suffix(path.suffix + ".silence.json")
        if cache.is_file():
            try:
                import json
                return [tuple(p) for p in json.loads(cache.read_text())]
            except Exception:
                # Cache corrupted -- regenerate.
                pass

        silences = await asyncio.to_thread(
            self._run_silencedetect, path
        )
        try:
            import json
            cache.write_text(json.dumps(silences))
        except OSError as exc:
            logger.info(
                "overlay_shorts_silence_cache_write_failed",
                extra={"path": str(cache), "error": str(exc)},
            )
        return silences

    def _run_silencedetect(self, path: Path) -> list[tuple[float, float]]:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=n={self._silence_db}dB:d={self._silence_min_dur_s}",
            "-f",
            "null",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out: list[tuple[float, float]] = []
        cur_start: float | None = None
        for line in proc.stderr.split("\n"):
            if "silence_start:" in line:
                try:
                    cur_start = float(
                        line.split("silence_start:")[1].strip().split()[0]
                    )
                except (ValueError, IndexError):
                    cur_start = None
            elif "silence_end:" in line and cur_start is not None:
                try:
                    end = float(
                        line.split("silence_end:")[1].strip().split()[0].rstrip("|")
                    )
                    out.append((cur_start, end))
                except (ValueError, IndexError):
                    pass
                cur_start = None
        return out
