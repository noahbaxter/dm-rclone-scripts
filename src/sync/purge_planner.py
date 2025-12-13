"""
Purge planning for DM Chart Sync.

Determines what files should be deleted (disabled drives, extra files, videos, partials).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional

from ..core.constants import VIDEO_EXTENSIONS, CHART_ARCHIVE_EXTENSIONS
from ..core.formatting import relative_posix, parent_posix
from .cache import scan_local_files
from .state import SyncState


def _is_archive(path: str) -> bool:
    """Check if a path is an archive file."""
    return any(path.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


@dataclass
class PurgeStats:
    """Detailed breakdown of what would be purged."""
    # Files from disabled drives/setlists
    chart_count: int = 0  # Actually file count (legacy naming)
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
    # Estimated chart count (archives = 1 chart each)
    estimated_charts: int = 0

    @property
    def total_files(self) -> int:
        return self.chart_count + self.extra_file_count + self.partial_count + self.video_count

    @property
    def total_size(self) -> int:
        return self.chart_size + self.extra_file_size + self.partial_size + self.video_size


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


def find_extra_files_sync_state(
    folder_name: str,
    folder_path: Path,
    sync_state: SyncState,
    local_files: dict = None,
) -> List[Tuple[Path, int]]:
    """
    Find local files not tracked in sync_state.

    This is the new simpler approach - anything on disk not in sync_state is extra.

    Args:
        folder_name: Name of the folder (for building sync state paths)
        folder_path: Path to the folder on disk
        sync_state: SyncState instance with tracked files
        local_files: Optional pre-scanned local files dict

    Returns:
        List of (Path, size) tuples for extra files
    """
    if local_files is None:
        local_files = scan_local_files(folder_path)
    if not local_files:
        return []

    # Get all tracked files from sync_state
    tracked_files = sync_state.get_all_files()

    # Find extras - files on disk not in sync_state
    extras = []
    for rel_path, size in local_files.items():
        # Build the full sync_state path (folder_name/rel_path)
        state_path = f"{folder_name}/{rel_path}"
        if state_path not in tracked_files:
            extras.append((folder_path / rel_path, size))

    return extras


def plan_purge(
    folders: list,
    base_path: Path,
    user_settings=None,
    sync_state: Optional[SyncState] = None,
) -> Tuple[List[Tuple[Path, int]], PurgeStats]:
    """
    Plan what files should be purged.

    This identifies:
    - Files from disabled drives/setlists
    - Extra files not in manifest (or not in sync_state if provided)
    - Partial downloads
    - Video files (when delete_videos is enabled)

    Args:
        folders: List of folder dicts from manifest
        base_path: Base download path
        user_settings: UserSettings instance for checking enabled states
        sync_state: SyncState instance for checking tracked files (optional)

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

        # Use cached local file scan
        local_files = scan_local_files(folder_path)
        if not local_files:
            continue

        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        if not drive_enabled:
            # Drive is disabled - count ALL local files as "charts" (includes partials)
            chart_parents = set()
            for rel_path, size in local_files.items():
                stats.chart_count += 1
                stats.chart_size += size
                all_files.append((folder_path / rel_path, size))
                # Estimate charts: archives are 1 chart, else group by parent folder
                if _is_archive(rel_path):
                    stats.estimated_charts += 1
                else:
                    chart_parents.add(parent_posix(rel_path))
            # Add unique parent folders as estimated charts
            stats.estimated_charts += len(chart_parents)
            continue

        # Only scan for partial downloads on ENABLED drives (rglob is expensive)
        partial_files = find_partial_downloads(folder_path)
        if partial_files:
            stats.partial_count += len(partial_files)
            stats.partial_size += sum(size for _, size in partial_files)
            stats.estimated_charts += len(partial_files)  # Each partial is 1 chart
            all_files.extend(partial_files)

        # Drive is enabled - count files in disabled setlists + extra files separately
        disabled_setlist_paths = set()
        disabled_chart_parents = set()

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
                # Estimate charts for disabled setlist files
                if _is_archive(rel_path):
                    stats.estimated_charts += 1
                else:
                    disabled_chart_parents.add(parent_posix(rel_path))
        # Add unique parent folders as estimated charts
        stats.estimated_charts += len(disabled_chart_parents)

        # Extra files not tracked in sync_state
        if sync_state:
            extras = find_extra_files_sync_state(folder_name, folder_path, sync_state, local_files)
        else:
            extras = []  # No sync_state = can't determine extras

        extra_paths = set()
        for f, size in extras:
            rel_path = relative_posix(f, folder_path)
            extra_paths.add(rel_path)
            if rel_path not in disabled_setlist_paths:
                stats.extra_file_count += 1
                stats.extra_file_size += size
                all_files.append((f, size))
                # Only count archive extras as charts
                if _is_archive(rel_path):
                    stats.estimated_charts += 1

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


def count_purgeable_files(
    folders: list,
    base_path: Path,
    user_settings=None,
    sync_state: Optional[SyncState] = None,
) -> Tuple[int, int, int]:
    """
    Count files that would be purged.

    Returns:
        Tuple of (total_files, total_size_bytes, estimated_charts)
    """
    _, stats = plan_purge(folders, base_path, user_settings, sync_state)
    return stats.total_files, stats.total_size, stats.estimated_charts


def count_purgeable_detailed(
    folders: list,
    base_path: Path,
    user_settings=None,
    sync_state: Optional[SyncState] = None,
) -> PurgeStats:
    """
    Count files that would be purged with detailed breakdown.

    Returns:
        PurgeStats with breakdown of charts vs extra files
    """
    _, stats = plan_purge(folders, base_path, user_settings, sync_state)
    return stats
