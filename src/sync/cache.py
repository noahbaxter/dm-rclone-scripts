"""
Filesystem cache for DM Chart Sync.

Provides cached scanning of local files and chart folders.
Cache is invalidated after downloads/purges.
"""

import os
from pathlib import Path

from ..stats import clear_local_stats_cache


class SyncCache:
    """Cache for expensive filesystem scan operations."""

    def __init__(self):
        self.local_files: dict[str, dict[str, int]] = {}  # folder_path -> {rel_path: size}
        self.actual_charts: dict[str, tuple[int, int]] = {}  # folder_path -> (count, size)

    def clear(self):
        """Clear all cached data (call after download/purge)."""
        self.local_files.clear()
        self.actual_charts.clear()

    def clear_folder(self, folder_path: str):
        """Clear cached data for a specific folder."""
        self.local_files.pop(folder_path, None)
        # Clear actual_charts for this folder and all subfolders
        to_remove = [k for k in self.actual_charts if k.startswith(folder_path)]
        for k in to_remove:
            self.actual_charts.pop(k, None)


# Global cache instance
_cache = SyncCache()


def get_cache() -> SyncCache:
    """Get the global cache instance."""
    return _cache


def clear_cache():
    """Clear the filesystem scan cache. Call after downloads or purges."""
    _cache.clear()
    clear_local_stats_cache()


def clear_folder_cache(folder_path: Path):
    """Clear cache for a specific folder. Call after downloading to that folder."""
    _cache.clear_folder(str(folder_path))
    clear_local_stats_cache(folder_path)


def scan_local_files(folder_path: Path) -> dict[str, int]:
    """
    Scan local folder and return dict of {relative_path: size}.

    Uses os.scandir for better performance than individual exists()/stat() calls.
    Results are cached until clear_cache() is called.
    """
    cache_key = str(folder_path)
    if cache_key in _cache.local_files:
        return _cache.local_files[cache_key]

    local_files = {}
    if not folder_path.exists():
        return local_files

    def scan_dir(dir_path: Path, prefix: str = ""):
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    rel_path = f"{prefix}{entry.name}" if prefix else entry.name
                    if entry.is_file(follow_symlinks=False):
                        try:
                            local_files[rel_path] = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        scan_dir(Path(entry.path), f"{rel_path}/")
        except OSError:
            pass

    scan_dir(folder_path)
    _cache.local_files[cache_key] = local_files
    return local_files


def _scan_actual_charts_uncached(folder_path: Path) -> tuple[int, int]:
    """
    Scan folder for actual chart folders (containing song.ini, notes.mid, etc).
    Internal uncached version.

    Returns:
        Tuple of (chart_count, total_size_bytes)
    """
    if not folder_path.exists():
        return 0, 0

    chart_count = 0
    total_size = 0
    chart_markers = {"song.ini", "notes.mid", "notes.chart"}

    def get_dir_size(dir_path: Path) -> int:
        size = 0
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        try:
                            size += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        size += get_dir_size(Path(entry.path))
        except OSError:
            pass
        return size

    def scan_for_charts(dir_path: Path):
        nonlocal chart_count, total_size
        try:
            has_marker = False
            with os.scandir(dir_path) as entries:
                subdirs = []
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        if entry.name.lower() in chart_markers:
                            has_marker = True
                    elif entry.is_dir(follow_symlinks=False):
                        subdirs.append(Path(entry.path))

                if has_marker:
                    chart_count += 1
                    total_size += get_dir_size(dir_path)
                else:
                    for subdir in subdirs:
                        scan_for_charts(subdir)
        except OSError:
            pass

    scan_for_charts(folder_path)
    return chart_count, total_size


def scan_actual_charts(folder_path: Path, disabled_setlists: set[str] = None) -> tuple[int, int]:
    """
    Scan folder for actual chart folders (containing song.ini, notes.mid, etc).
    Results are cached until clear_cache() is called.

    Args:
        folder_path: Path to scan
        disabled_setlists: Set of top-level subfolder names to skip

    Returns:
        Tuple of (chart_count, total_size_bytes)
    """
    cache_key = str(folder_path)

    # Get or compute full scan (no filtering)
    if cache_key in _cache.actual_charts:
        full_count, full_size = _cache.actual_charts[cache_key]
    else:
        full_count, full_size = _scan_actual_charts_uncached(folder_path)
        _cache.actual_charts[cache_key] = (full_count, full_size)

    if not disabled_setlists:
        return full_count, full_size

    # Subtract disabled setlists (each cached separately)
    result_count = full_count
    result_size = full_size

    for setlist_name in disabled_setlists:
        setlist_path = folder_path / setlist_name
        setlist_key = str(setlist_path)

        if setlist_key in _cache.actual_charts:
            setlist_count, setlist_size = _cache.actual_charts[setlist_key]
        else:
            setlist_count, setlist_size = _scan_actual_charts_uncached(setlist_path)
            _cache.actual_charts[setlist_key] = (setlist_count, setlist_size)

        result_count -= setlist_count
        result_size -= setlist_size

    return max(0, result_count), max(0, result_size)
