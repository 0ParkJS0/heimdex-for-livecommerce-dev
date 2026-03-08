"""YouTube S3 key helpers — standalone, pure functions.

Mirrors ``drive_keys.py`` pattern.  Only ``hashlib`` dependency.
Workers and the API use these functions to generate identical S3 keys.
"""

import hashlib


def youtube_video_id(org_id: str, yt_video_id: str) -> str:
    """Deterministic video_id for YouTube videos.

    Format: ``yt_{sha256(org_id:yt_video_id)[:16]}``.
    Collision-resistant, idempotent.
    """
    digest = hashlib.sha256(f"{org_id}:{yt_video_id}".encode()).hexdigest()[:16]
    return f"yt_{digest}"


def youtube_original_s3_key(org_id: str, channel_id: str, yt_video_id: str) -> str:
    """S3 key for the original (pre-transcode) video uploaded by youtube-worker."""
    return f"{org_id}/youtube/{channel_id}/{yt_video_id}/original.mp4"


def youtube_subtitle_s3_key(org_id: str, channel_id: str, yt_video_id: str) -> str:
    """S3 key for extracted Korean subtitle (VTT format)."""
    return f"{org_id}/youtube/{channel_id}/{yt_video_id}/subtitles.ko.vtt"


def youtube_metadata_s3_key(org_id: str, channel_id: str, yt_video_id: str) -> str:
    """S3 key for yt-dlp metadata JSON."""
    return f"{org_id}/youtube/{channel_id}/{yt_video_id}/metadata.json"


def youtube_thumbnail_s3_key(org_id: str, video_id: str, scene_id: str) -> str:
    """S3 key for scene thumbnail (reuses drive thumbnail namespace for consistency)."""
    return f"{org_id}/youtube/thumbs/{video_id}/{scene_id}.jpg"


def youtube_thumbnail_s3_prefix(org_id: str, video_id: str) -> str:
    """S3 prefix for all thumbnails of a YouTube video."""
    return f"{org_id}/youtube/thumbs/{video_id}/"


def youtube_keyframe_s3_prefix(org_id: str, video_id: str) -> str:
    """S3 prefix for enrichment keyframes of a YouTube video."""
    return f"{org_id}/youtube/keyframes/{video_id}/"


def youtube_keyframe_s3_key(org_id: str, video_id: str, scene_id: str) -> str:
    """S3 key for a single enrichment keyframe."""
    return f"{org_id}/youtube/keyframes/{video_id}/{scene_id}.jpg"


def youtube_audio_s3_key(org_id: str, video_id: str) -> str:
    """S3 key for extracted audio (WAV)."""
    return f"{org_id}/youtube/audio/{video_id}/audio.wav"


def youtube_scene_manifest_s3_key(org_id: str, video_id: str) -> str:
    """S3 key for scene manifest JSON."""
    return f"{org_id}/youtube/manifests/{video_id}/scenes.json"
