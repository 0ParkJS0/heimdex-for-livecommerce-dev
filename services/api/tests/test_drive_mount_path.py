"""Unit tests for the shared Drive mount-relative path helper.

This logic is shared by the Premiere export and the HQ agent export, so it's
pinned here. Cases for ``drive``/``folder``/None reproduce the historical
Premiere-export behavior; ``my_drive``/``shared_drive`` cover the gap the old
inline logic dropped to a bare path.
"""

from __future__ import annotations

from app.lib.drive_mount_path import build_mount_relative_path


def test_shared_drive_scope():
    assert build_mount_relative_path(
        scope_type="drive", drive_name="Footage", folder_path=None,
        drive_path="2026-05/clip.mp4",
    ) == "Shared drives/Footage/2026-05/clip.mp4"


def test_shared_drive_new_scope_value():
    # newer "shared_drive" scope behaves like legacy "drive"
    assert build_mount_relative_path(
        scope_type="shared_drive", drive_name="Footage", folder_path=None,
        drive_path="clip.mp4",
    ) == "Shared drives/Footage/clip.mp4"


def test_folder_scope_uses_folder_path_verbatim():
    # folder_path already carries the My-Drive (or localized) prefix
    assert build_mount_relative_path(
        scope_type="folder", drive_name=None, folder_path="My Drive/Marketing/Q2",
        drive_path="livestream.mp4",
    ) == "My Drive/Marketing/Q2/livestream.mp4"


def test_folder_scope_korean_prefix_preserved():
    assert build_mount_relative_path(
        scope_type="folder", drive_name=None, folder_path="내 드라이브/촬영",
        drive_path="a.mp4",
    ) == "내 드라이브/촬영/a.mp4"


def test_my_drive_scope_gets_my_drive_prefix():
    # The gap the old inline export logic dropped to a bare path.
    assert build_mount_relative_path(
        scope_type="my_drive", drive_name=None, folder_path=None,
        drive_path="sub/a.mp4",
    ) == "My Drive/sub/a.mp4"


def test_drive_scope_without_name_falls_back():
    assert build_mount_relative_path(
        scope_type="drive", drive_name=None, folder_path=None, drive_path="a.mp4",
    ) == "a.mp4"


def test_unknown_scope_falls_back_to_bare_path():
    assert build_mount_relative_path(
        scope_type="", drive_name=None, folder_path=None, drive_path="a.mp4",
    ) == "a.mp4"


def test_leading_slash_on_drive_path_stripped():
    assert build_mount_relative_path(
        scope_type="my_drive", drive_name=None, folder_path=None,
        drive_path="/a.mp4",
    ) == "My Drive/a.mp4"


def test_folder_path_trailing_slash_normalized():
    assert build_mount_relative_path(
        scope_type="folder", drive_name=None, folder_path="My Drive/x/",
        drive_path="a.mp4",
    ) == "My Drive/x/a.mp4"
