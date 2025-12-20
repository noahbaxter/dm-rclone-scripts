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

    For regular files: check if exists with matching size (or sync_state if available).
    For archives: check if sync_state has matching MD5.

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
    is_windows = os.name == 'nt'

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

        if is_archive_file(file_name):
            # Archive file: check if synced via sync_state
            local_path = local_base / file_path
            chart_folder = local_path.parent

            # Check for long path on Windows
            download_path = chart_folder / f"_download_{file_name}"
            if is_windows and len(str(download_path)) >= WINDOWS_MAX_PATH:
                long_paths.append(file_path)
                continue

            is_synced = False
            if sync_state and sync_state.is_archive_synced(rel_path, file_md5):
                # Also verify extracted files still exist
                archive_files = sync_state.get_archive_files(rel_path)
                missing = sync_state.check_files_exist(archive_files)
                is_synced = len(missing) == 0

            if is_synced:
                skipped += 1
            else:
                # Need to download and extract
                to_download.append(DownloadTask(
                    file_id=f["id"],
                    local_path=download_path,
                    size=file_size,
                    md5=file_md5,
                    is_archive=True,
                    rel_path=rel_path,
                ))
        else:
            # Regular file: check if exists with matching size
            local_path = local_base / file_path

            # Skip video files if delete_videos is enabled
            if delete_videos and Path(file_name).suffix.lower() in VIDEO_EXTENSIONS:
                skipped += 1
                continue

            # Check for long path on Windows
            if is_windows and len(str(local_path)) >= WINDOWS_MAX_PATH:
                long_paths.append(file_path)
                continue

            # Check if file is already synced
            if sync_state and sync_state.is_file_synced(rel_path, file_size):
                # sync_state tracks this file with matching size - trust it
                is_synced = True
            else:
                # Not in sync_state - check if file exists on disk with correct size
                # (file_size is from manifest, so this validates local matches manifest)
                # Handles: migration from rclone, recovery after deleting sync_state.json
                is_synced = file_exists_with_size(local_path, file_size)

            if is_synced:
                skipped += 1
            else:
                to_download.append(DownloadTask(
                    file_id=f["id"],
                    local_path=local_path,
                    size=file_size,
                    md5=file_md5,
                    rel_path=rel_path,
                ))

    return to_download, skipped, long_paths
