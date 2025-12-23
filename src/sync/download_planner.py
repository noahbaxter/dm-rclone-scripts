"""
Download planning for DM Chart Sync.

Determines what files need to be downloaded by comparing manifest to local state.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional

from ..core.constants import CHART_ARCHIVE_EXTENSIONS, VIDEO_EXTENSIONS
from ..core.files import file_exists_with_size
from ..core.formatting import sanitize_path
from .state import SyncState

# Windows MAX_PATH limit (260 chars including null terminator)
WINDOWS_MAX_PATH = 260


def is_long_paths_enabled() -> bool:
    """Check if Windows long paths are enabled in registry."""
    if os.name != 'nt':
        return True
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem"
        )
        value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
        winreg.CloseKey(key)
        return value == 1
    except (OSError, FileNotFoundError):
        return False


def exceeds_windows_path_limit(path: Path) -> bool:
    """Check if path exceeds Windows MAX_PATH and long paths aren't enabled."""
    return os.name == 'nt' and not is_long_paths_enabled() and len(str(path)) >= WINDOWS_MAX_PATH


@dataclass
class DownloadTask:
    """A file to be downloaded."""
    file_id: str
    local_path: Path
    size: int = 0
    md5: str = ""
    is_archive: bool = False  # If True, needs extraction after download
    rel_path: str = ""  # Relative path in manifest (for sync state tracking)


def is_archive_file(filename: str) -> bool:
    """Check if a filename is an archive type we handle."""
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


def plan_downloads(
    files: List[dict],
    local_base: Path,
    delete_videos: bool = True,
    sync_state: Optional[SyncState] = None,
    folder_name: str = "",
) -> Tuple[List[DownloadTask], int, List[str]]:
    """
    Plan which files need to be downloaded.

    For regular files: check if exists on disk with matching size (manifest is source of truth).
    For archives: check if sync_state has matching MD5 and extracted files exist.

    Args:
        files: List of file dicts with id, path, size keys
        local_base: Base path for local files
        delete_videos: Whether to skip video files
        sync_state: SyncState instance for checking sync status (optional)
        folder_name: Name of the folder being synced (for building rel_path)

    Returns:
        Tuple of (tasks_to_download, skipped_count, long_paths)
        long_paths: List of paths that exceed Windows MAX_PATH (only on Windows)
    """
    to_download = []
    skipped = 0
    long_paths = []

    for f in files:
        # Sanitize path for Windows-illegal characters (*, ?, ", <, >, |, :)
        file_path = sanitize_path(f["path"])
        file_name = file_path.split("/")[-1] if "/" in file_path else file_path
        file_size = f.get("size", 0)
        file_md5 = f.get("md5", "")

        # Build relative path for sync state (folder_name/file_path)
        rel_path = f"{folder_name}/{file_path}" if folder_name else file_path

        # Skip Google Docs/Sheets (no MD5 AND no file extension = can't download as binary)
        # Regular files have MD5s; even extensionless files like _rb3con have MD5s
        if not file_md5 and "." not in file_name:
            skipped += 1
            continue

        is_archive = is_archive_file(file_name)
        local_path = local_base / file_path

        # Archives download to temp path, regular files download directly
        if is_archive:
            download_path = local_path.parent / f"_download_{file_name}"
        else:
            download_path = local_path
            # Skip video files if delete_videos is enabled
            if delete_videos and Path(file_name).suffix.lower() in VIDEO_EXTENSIONS:
                skipped += 1
                continue

        # Check for long path on Windows (only if long paths not enabled)
        if exceeds_windows_path_limit(download_path):
            long_paths.append(file_path)
            continue

        # Check if already synced
        if is_archive:
            is_synced = False
            if sync_state and sync_state.is_archive_synced(rel_path, file_md5):
                # Also verify extracted files still exist
                archive_files = sync_state.get_archive_files(rel_path)
                missing = sync_state.check_files_exist(archive_files)
                is_synced = len(missing) == 0
        else:
            is_synced = file_exists_with_size(local_path, file_size)

        # Add to download list or skip
        if is_synced:
            skipped += 1
        else:
            to_download.append(DownloadTask(
                file_id=f["id"],
                local_path=download_path,
                size=file_size,
                md5=file_md5,
                is_archive=is_archive,
                rel_path=rel_path,
            ))

    return to_download, skipped, long_paths
