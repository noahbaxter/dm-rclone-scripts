"""
Archive inspection for manifest generation.

Reads archive contents without extracting to calculate size without video files.
"""

import zipfile
from pathlib import Path
from typing import Optional, Tuple

from ..constants import VIDEO_EXTENSIONS

# Optional archive format support
try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False

try:
    from unrar import rarfile as unrar_rarfile
    unrar_rarfile.RarFile
    HAS_RAR = True
except (ImportError, LookupError):
    HAS_RAR = False


def get_archive_size_without_videos(archive_path: Path) -> Optional[int]:
    """
    Calculate the uncompressed size of an archive excluding video files.

    Reads archive metadata without extracting.

    Args:
        archive_path: Path to the archive file

    Returns:
        Total uncompressed size of non-video files, or None if can't read archive
    """
    suffix = archive_path.suffix.lower()

    try:
        if suffix == ".zip":
            return _get_zip_size_without_videos(archive_path)
        elif suffix == ".7z" and HAS_7Z:
            return _get_7z_size_without_videos(archive_path)
        elif suffix == ".rar" and HAS_RAR:
            return _get_rar_size_without_videos(archive_path)
    except Exception:
        pass

    return None


def _is_video_file(filename: str) -> bool:
    """Check if a filename is a video file."""
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def _get_zip_size_without_videos(archive_path: Path) -> int:
    """Get size of zip contents excluding video files."""
    total_size = 0
    with zipfile.ZipFile(archive_path, 'r') as zf:
        for info in zf.infolist():
            if not info.is_dir() and not _is_video_file(info.filename):
                total_size += info.file_size
    return total_size


def _get_7z_size_without_videos(archive_path: Path) -> int:
    """Get size of 7z contents excluding video files."""
    total_size = 0
    with py7zr.SevenZipFile(archive_path, 'r') as szf:
        for entry in szf.list():
            if not entry.is_directory and not _is_video_file(entry.filename):
                total_size += entry.uncompressed
    return total_size


def _get_rar_size_without_videos(archive_path: Path) -> int:
    """Get size of rar contents excluding video files."""
    total_size = 0
    with unrar_rarfile.RarFile(str(archive_path)) as rf:
        for info in rf.infolist():
            if not info.is_dir() and not _is_video_file(info.filename):
                total_size += info.file_size
    return total_size
