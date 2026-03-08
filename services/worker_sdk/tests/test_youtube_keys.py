"""Tests for heimdex_worker_sdk.youtube_keys — YouTube S3 key builders."""

import hashlib

import pytest

from heimdex_worker_sdk.youtube_keys import (
    youtube_audio_s3_key,
    youtube_keyframe_s3_key,
    youtube_keyframe_s3_prefix,
    youtube_metadata_s3_key,
    youtube_original_s3_key,
    youtube_scene_manifest_s3_key,
    youtube_subtitle_s3_key,
    youtube_thumbnail_s3_key,
    youtube_thumbnail_s3_prefix,
    youtube_video_id,
)


class TestYouTubeVideoId:
    def test_deterministic(self):
        a = youtube_video_id("org1", "dQw4w9WgXcQ")
        b = youtube_video_id("org1", "dQw4w9WgXcQ")
        assert a == b

    def test_format(self):
        vid = youtube_video_id("org1", "dQw4w9WgXcQ")
        assert vid.startswith("yt_")
        assert len(vid) == 3 + 16  # "yt_" + 16 hex chars

    def test_different_inputs(self):
        a = youtube_video_id("org1", "video1")
        b = youtube_video_id("org1", "video2")
        c = youtube_video_id("org2", "video1")
        assert a != b
        assert a != c

    def test_matches_manual_computation(self):
        digest = hashlib.sha256("org1:dQw4w9WgXcQ".encode()).hexdigest()[:16]
        expected = f"yt_{digest}"
        assert youtube_video_id("org1", "dQw4w9WgXcQ") == expected

    def test_does_not_collide_with_drive_ids(self):
        """YouTube IDs use 'yt_' prefix, Drive IDs use 'gd_' prefix."""
        from heimdex_worker_sdk.drive_keys import drive_video_id

        yt = youtube_video_id("org1", "file1")
        gd = drive_video_id("org1", "file1")
        assert yt != gd
        assert yt.startswith("yt_")
        assert gd.startswith("gd_")


class TestYouTubeS3Keys:
    def test_original_s3_key(self):
        key = youtube_original_s3_key("org1", "UCchan", "vid123")
        assert key == "org1/youtube/UCchan/vid123/original.mp4"

    def test_subtitle_s3_key(self):
        key = youtube_subtitle_s3_key("org1", "UCchan", "vid123")
        assert key == "org1/youtube/UCchan/vid123/subtitles.ko.vtt"

    def test_metadata_s3_key(self):
        key = youtube_metadata_s3_key("org1", "UCchan", "vid123")
        assert key == "org1/youtube/UCchan/vid123/metadata.json"

    def test_thumbnail_s3_key(self):
        key = youtube_thumbnail_s3_key("org1", "yt_abc123", "yt_abc123_scene_0")
        assert key == "org1/youtube/thumbs/yt_abc123/yt_abc123_scene_0.jpg"

    def test_thumbnail_s3_prefix(self):
        prefix = youtube_thumbnail_s3_prefix("org1", "yt_abc123")
        assert prefix == "org1/youtube/thumbs/yt_abc123/"

    def test_keyframe_s3_prefix(self):
        prefix = youtube_keyframe_s3_prefix("org1", "yt_abc123")
        assert prefix == "org1/youtube/keyframes/yt_abc123/"

    def test_keyframe_s3_key(self):
        key = youtube_keyframe_s3_key("org1", "yt_abc123", "yt_abc123_scene_0")
        assert key == "org1/youtube/keyframes/yt_abc123/yt_abc123_scene_0.jpg"

    def test_audio_s3_key(self):
        key = youtube_audio_s3_key("org1", "yt_abc123")
        assert key == "org1/youtube/audio/yt_abc123/audio.wav"

    def test_scene_manifest_s3_key(self):
        key = youtube_scene_manifest_s3_key("org1", "yt_abc123")
        assert key == "org1/youtube/manifests/yt_abc123/scenes.json"


class TestYouTubeKeyConsistency:
    """Verify that prefixes are proper prefixes of full keys."""

    def test_keyframe_prefix_matches_key(self):
        prefix = youtube_keyframe_s3_prefix("org1", "yt_vid1")
        key = youtube_keyframe_s3_key("org1", "yt_vid1", "yt_vid1_scene_0")
        assert key.startswith(prefix)

    def test_thumbnail_prefix_matches_key(self):
        prefix = youtube_thumbnail_s3_prefix("org1", "yt_vid1")
        key = youtube_thumbnail_s3_key("org1", "yt_vid1", "yt_vid1_scene_0")
        assert key.startswith(prefix)

    def test_youtube_namespace_isolated_from_drive(self):
        """YouTube keys use /youtube/ namespace, Drive uses /drive/."""
        yt_key = youtube_original_s3_key("org1", "UCchan", "vid123")
        from heimdex_worker_sdk.drive_keys import proxy_s3_key

        drive_key = proxy_s3_key("org1", "drive1", "gfile1")
        assert "/youtube/" in yt_key
        assert "/drive/" in drive_key
        assert "/youtube/" not in drive_key
        assert "/drive/" not in yt_key
