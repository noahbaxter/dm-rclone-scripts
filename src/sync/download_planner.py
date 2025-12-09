"""
Download planning for DM Chart Sync.

Determines what files need to be downloaded by comparing manifest to local state.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from ..constants import CHART_ARCHIVE_EXTENSIONS, VIDEO_EXTENSIONS
from ..file_ops import file_exists_with_size
from ..utils import sanitize_path
from .checksum import read_checksum

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


def is_archive_file(filename: str) -> bool:
    """Check if a filename is an archive type we handle."""
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


def plan_downloads(
    files: List[dict],
    local_base: Path,
    delete_videos: bool = True,
) -> Tuple[List[DownloadTask], int, List[str]]:
    """
    Plan which files need to be downloaded.

    For regular files: check if exists with matching size.
    For archives: check if check.txt has matching MD5.

    Args:
        files: List of file dicts with id, path, size keys
        local_base: Base path for local files
        delete_videos: Whether to skip video files

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

        # Skip Google Docs/Sheets (no MD5 AND no file extension = can't download as binary)
        # Regular files have MD5s; even extensionless files like _rb3con have MD5s
        if not file_md5 and "." not in file_name:
            skipped += 1
            continue

        if is_archive_file(file_name):
            # Archive file: check MD5 in check.txt
            # The chart folder is the parent of where the archive would be
            local_path = local_base / file_path
            chart_folder = local_path.parent

            # Check for long path on Windows
            download_path = chart_folder / f"_download_{file_name}"
            if is_windows and len(str(download_path)) >= WINDOWS_MAX_PATH:
                long_paths.append(file_path)
                continue

            stored_md5 = read_checksum(chart_folder, archive_name=file_name)
            if stored_md5 and stored_md5 == file_md5:
                # Already extracted with matching checksum
                skipped += 1
            else:
                # Need to download and extract
                # Download to temp location within chart folder
                to_download.append(DownloadTask(
                    file_id=f["id"],
                    local_path=download_path,
                    size=file_size,
                    md5=file_md5,
                    is_archive=True,
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

            if file_exists_with_size(local_path, file_size):
                skipped += 1
            else:
                to_download.append(DownloadTask(
                    file_id=f["id"],
                    local_path=local_path,
                    size=file_size,
                    md5=file_md5,
                ))

    return to_download, skipped, long_paths
