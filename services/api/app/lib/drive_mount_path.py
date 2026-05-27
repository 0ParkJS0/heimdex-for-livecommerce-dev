"""Pure mount-relative path assembly for Google Drive Desktop originals.

Both the Premiere export (FCPXML local paths) and the high-quality agent export
need to locate a DriveFile's ORIGINAL on a locally-mounted Google Drive Desktop
folder. The agent supplies the mount root (e.g.
``~/Library/CloudStorage/GoogleDrive-<account>``); this returns the path
RELATIVE to that root, so callers just join ``f"{mount}/{rel}"``.

``drive_path`` is stored relative to the connection root during discovery, so the
prefix depends on the connection scope:

  - shared drives mount as ``Shared drives/<drive_name>/...``
  - whole-My-Drive connections mount as ``My Drive/...``
  - folder-scoped connections store ``folder_path`` already including the
    My-Drive (or localized) prefix, so it is used verbatim

Localization caveat: on a Korean-locale Google Drive Desktop the My-Drive folder
is named ``내 드라이브`` on disk, not ``My Drive``. The HQ-export agent resolves
the file under its mount and VERIFIES it by size/md5, falling back to the
localized folder name on a miss — see the agent phase. This helper emits the
canonical English name as the primary guess.
"""

from __future__ import annotations

_SHARED_DRIVE_SCOPES = frozenset({"drive", "shared_drive"})


def build_mount_relative_path(
    *,
    scope_type: str,
    drive_name: str | None,
    folder_path: str | None,
    drive_path: str,
) -> str:
    """Return the path of a Drive file relative to the local mount root.

    Args:
        scope_type: DriveConnection.scope_type (``drive``/``shared_drive``/
            ``folder``/``my_drive``).
        drive_name: Shared Drive display name (for shared-drive scopes).
        folder_path: Connection folder path (for folder scopes); already
            includes the My-Drive prefix.
        drive_path: DriveFile.drive_path — path relative to the connection root.
            Callers should pass ``df.drive_path or df.file_name``.
    """
    drive_path = drive_path.lstrip("/")
    if scope_type in _SHARED_DRIVE_SCOPES and drive_name:
        return f"Shared drives/{drive_name}/{drive_path}"
    if scope_type == "folder" and folder_path:
        return f"{folder_path.strip('/')}/{drive_path}"
    if scope_type == "my_drive":
        return f"My Drive/{drive_path}"
    # Unknown / underspecified scope: bare path under the mount root. Matches the
    # historical Premiere-export fallback.
    return drive_path
