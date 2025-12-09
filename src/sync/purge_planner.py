"""
Purge planning for DM Chart Sync.

Determines what files should be deleted (disabled drives, extra files, videos, partials).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from ..constants import VIDEO_EXTENSIONS, CHART_ARCHIVE_EXTENSIONS
from ..utils import sanitize_path
from .cache import scan_local_files, scan_checksums


@dataclass
class PurgeStats:
    """Detailed breakdown of what would be purged."""
    # Charts from disabled drives/setlists
    chart_count: int = 0
    chart_size: int = 0
    # Extra files not in manifest
    extra_file_count: int = 0
    extra_file_size: int = 0
    # Partial downloads
    partial_count: int = 0
    partial_size: int = 0
    # Video files (when delete_videos is enabled)
    video_count: int = 0
    video_size: int = 0

    @property
    def total_files(self) -> int:
        return self.chart_count + self.extra_file_count + self.partial_count + self.video_count

    @property
    def total_size(self) -> int:
        return self.chart_size + self.extra_file_size + self.partial_size + self.video_size


def is_archive_file(filename: str) -> bool:
    """Check if a filename is an archive type we handle."""
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


def _check_archive_synced(checksums: dict, checksum_path: str, archive_name: str, manifest_md5: str) -> tuple[bool, int]:
    """Check if an archive is synced by comparing checksum data."""
    checksum_data = checksums.get(checksum_path, {})
    stored_md5 = None
    extracted_size = 0
    has_entry = False

    if "archives" in checksum_data:
        archive_info = checksum_data["archives"].get(archive_name, {})
        if archive_info:
            has_entry = True
            stored_md5 = archive_info.get("md5", "")
            extracted_size = archive_info.get("size", 0)
    elif "md5" in checksum_data:
        has_entry = True
        stored_md5 = checksum_data.get("md5", "")
        extracted_size = checksum_data.get("size", 0)

    is_synced = has_entry and stored_md5 == manifest_md5
    return is_synced, extracted_size


def find_partial_downloads(base_path: Path) -> List[Tuple[Path, int]]:
    """
    Find partial download files (files with _download_ prefix).

    These are incomplete archive downloads that were interrupted and can't be resumed.

    Args:
        base_path: Base download path to scan

    Returns:
        List of (Path, size) tuples for partial download files
    """
    partial_files = []
    if not base_path.exists():
        return partial_files

    for f in base_path.rglob("_download_*"):
        if f.is_file():
            try:
                partial_files.append((f, f.stat().st_size))
            except Exception:
                partial_files.append((f, 0))

    return partial_files


def find_extra_files(folder: dict, base_path: Path, local_files: dict = None) -> List[Tuple[Path, int]]:
    """
    Find local files not in the manifest.

    For archive charts, if check.txt exists with matching MD5, the entire
    chart folder is considered valid (extracted contents are expected).

    Args:
        folder: Folder dict from manifest
        base_path: Base download path
        local_files: Optional pre-scanned local files dict from scan_local_files().
                     If not provided, will scan (but prefer passing cached data).

    Returns list of (Path, size) tuples.
    """
    manifest_files = folder.get("files")
    if not manifest_files:
        return []

    folder_path = base_path / folder["name"]

    # Use cached local_files if provided, otherwise scan
    if local_files is None:
        local_files = scan_local_files(folder_path)
    if not local_files:
        return []

    # CRITICAL: Use sanitized paths to match actual filenames on disk
    # Downloads use sanitize_path() which replaces illegal chars (: ? * etc.)
    expected_paths = {sanitize_path(f["path"]) for f in manifest_files}

    # Build a set of chart folders that have valid check.txt (synced archive charts)
    # These folders should be entirely skipped during purge
    valid_archive_prefixes = set()
    checksums = scan_checksums(folder_path)

    for f in manifest_files:
        file_path = f.get("path", "")
        file_name = file_path.split("/")[-1].lower() if "/" in file_path else file_path.lower()
        file_md5 = f.get("md5", "")

        if is_archive_file(file_name) and file_md5:
            # This is an archive file - check if it's been extracted
            sanitized = sanitize_path(file_path)
            if "/" in file_path:
                parent = "/".join(sanitized.split("/")[:-1])
            else:
                # Root-level archive - check.txt is in folder root
                parent = ""
            # Get original archive name (not lowercased) for check.txt lookup
            archive_name = sanitized.split("/")[-1] if "/" in sanitized else sanitized
            # Use cached checksums instead of reading each file
            is_synced, _ = _check_archive_synced(checksums, parent, archive_name, file_md5)
            if is_synced:
                # This archive has been extracted - mark folder prefix as valid
                valid_archive_prefixes.add(parent + "/" if parent else "")

    # Find extra files using cached local_files dict
    filtered_extras = []
    for rel_path, size in local_files.items():
        # Skip if in expected paths
        if rel_path in expected_paths:
            continue

        # Check if this file is inside a valid archive folder
        is_in_valid_archive = False
        for valid_prefix in valid_archive_prefixes:
            if valid_prefix and rel_path.startswith(valid_prefix):
                is_in_valid_archive = True
                break

        if not is_in_valid_archive:
            filtered_extras.append((folder_path / rel_path, size))

    return filtered_extras


def plan_purge(folders: list, base_path: Path, user_settings=None) -> Tuple[List[Tuple[Path, int]], PurgeStats]:
    """
    Plan what files should be purged.

    This identifies:
    - Files from disabled drives/setlists
    - Extra files not in manifest
    - Partial downloads
    - Video files (when delete_videos is enabled)

    Args:
        folders: List of folder dicts from manifest
        base_path: Base download path
        user_settings: UserSettings instance for checking enabled states

    Returns:
        Tuple of (files_to_purge, stats)
        files_to_purge is a list of (Path, size) tuples
    """
    stats = PurgeStats()
    all_files = []

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name

        if not folder_path.exists():
            continue

        # Count partial downloads within this folder BEFORE checking drive enabled
        partial_files = find_partial_downloads(folder_path)
        if partial_files:
            stats.partial_count += len(partial_files)
            stats.partial_size += sum(size for _, size in partial_files)
            all_files.extend(partial_files)

        # Use cached local file scan
        local_files = scan_local_files(folder_path)
        if not local_files:
            continue

        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        if not drive_enabled:
            # Drive is disabled - count ALL local files as "charts"
            for rel_path, size in local_files.items():
                stats.chart_count += 1
                stats.chart_size += size
                all_files.append((folder_path / rel_path, size))
            continue

        # Drive is enabled - count files in disabled setlists + extra files separately
        disabled_setlist_paths = set()

        # Get disabled setlists
        disabled_setlists = user_settings.get_disabled_subfolders(folder_id) if user_settings else set()

        # Count files in disabled setlists
        for rel_path, size in local_files.items():
            first_slash = rel_path.find("/")
            setlist_name = rel_path[:first_slash] if first_slash != -1 else rel_path
            if setlist_name in disabled_setlists:
                disabled_setlist_paths.add(rel_path)
                stats.chart_count += 1
                stats.chart_size += size
                all_files.append((folder_path / rel_path, size))

        # Extra files not in manifest
        extras = find_extra_files(folder, base_path, local_files)
        extra_paths = set()
        for f, size in extras:
            rel_path = str(f.relative_to(folder_path))
            extra_paths.add(rel_path)
            if rel_path not in disabled_setlist_paths:
                stats.extra_file_count += 1
                stats.extra_file_size += size
                all_files.append((f, size))

        # Count video files when delete_videos is enabled
        delete_videos = user_settings.delete_videos if user_settings else True
        if delete_videos:
            for rel_path, size in local_files.items():
                if rel_path in disabled_setlist_paths or rel_path in extra_paths:
                    continue
                if Path(rel_path).suffix.lower() in VIDEO_EXTENSIONS:
                    stats.video_count += 1
                    stats.video_size += size
                    all_files.append((folder_path / rel_path, size))

    # Deduplicate (some files may be counted in multiple categories)
    seen = set()
    unique_files = []
    for f, size in all_files:
        if f not in seen:
            seen.add(f)
            unique_files.append((f, size))

    return unique_files, stats


def count_purgeable_files(folders: list, base_path: Path, user_settings=None) -> Tuple[int, int]:
    """
    Count files that would be purged (backward-compatible wrapper).

    Returns:
        Tuple of (total_files, total_size_bytes)
    """
    _, stats = plan_purge(folders, base_path, user_settings)
    return stats.total_files, stats.total_size


def count_purgeable_detailed(folders: list, base_path: Path, user_settings=None) -> PurgeStats:
    """
    Count files that would be purged with detailed breakdown.

    Returns:
        PurgeStats with breakdown of charts vs extra files
    """
    _, stats = plan_purge(folders, base_path, user_settings)
    return stats
