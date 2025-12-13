"""
Stats module for DM Chart Sync.

Provides accurate chart statistics by combining multiple data sources:
1. Local disk scan (most accurate for downloaded/extracted content)
2. Admin overrides (for static content with known values)
3. Manifest data (fallback)
"""

from pathlib import Path
from typing import Optional

from .local import (
    LocalStatsScanner,
    SetlistStats,
    FolderStats,
    get_scanner,
    clear_local_stats_cache,
    scan_folder_charts,
    scan_setlist_charts,
)
from .overrides import (
    ManifestOverrides,
    SetlistOverride,
    FolderOverride,
    get_overrides,
    reload_overrides,
)


__all__ = [
    # Local scanning
    "LocalStatsScanner",
    "SetlistStats",
    "FolderStats",
    "get_scanner",
    "clear_local_stats_cache",
    "scan_folder_charts",
    "scan_setlist_charts",
    # Overrides
    "ManifestOverrides",
    "SetlistOverride",
    "FolderOverride",
    "get_overrides",
    "reload_overrides",
    # Integration
    "get_best_stats",
]


def get_best_stats(
    folder_name: str,
    setlist_name: str,
    manifest_charts: int,
    manifest_size: int,
    local_path: Optional[Path] = None,
    scanner: Optional[LocalStatsScanner] = None,
    overrides: Optional[ManifestOverrides] = None,
) -> tuple[int, int]:
    """
    Get best available chart count and size from multiple sources.

    Chart count priority (highest to lowest):
    1. Local disk scan (if folder exists and has extracted content)
    2. Admin override (for nested archives like game rips)
    3. Manifest data (fallback)

    Size priority:
    1. Local disk scan (actual extracted size on disk)
    2. Manifest data (archive/download size) - overrides don't affect size

    Args:
        folder_name: Name of the drive folder
        setlist_name: Name of the setlist
        manifest_charts: Chart count from manifest
        manifest_size: Total size from manifest
        local_path: Path to the local download folder (or None if not downloaded)
        scanner: LocalStatsScanner instance (or None to use default)
        overrides: ManifestOverrides instance (or None to use default)

    Returns:
        Tuple of (chart_count, total_size)
    """
    # Get default instances if not provided
    if scanner is None:
        scanner = get_scanner()
    if overrides is None:
        overrides = get_overrides()

    # 1. Try local scan first (most accurate for downloaded content)
    if local_path is not None:
        setlist_path = local_path / setlist_name
        if setlist_path.exists():
            stats = scanner.get_setlist_stats(setlist_path)
            if stats.chart_count > 0:
                # Local scan found charts - use this as the source of truth
                return stats.chart_count, stats.total_size

    # 2. Try admin override for chart count (size always from manifest - it's the download size)
    override = overrides.get_setlist_override(folder_name, setlist_name)
    if override is not None and override.chart_count is not None:
        return override.chart_count, manifest_size

    # 3. Fall back to manifest data
    return manifest_charts, manifest_size
