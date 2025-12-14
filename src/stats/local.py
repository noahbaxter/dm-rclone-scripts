"""
Local filesystem scanning module for chart statistics.

This module provides accurate chart counts by scanning the actual downloaded
and extracted content on disk, which is more reliable than manifest data
(especially for nested archives like game rips).
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.constants import CHART_MARKERS


@dataclass
class SetlistStats:
    """Stats for a single setlist folder."""
    name: str
    chart_count: int = 0       # Actual chart folders found
    total_size: int = 0        # Total extracted size in bytes
    archive_count: int = 0     # Number of archive files (for comparison)
    scanned_at: float = 0.0    # Unix timestamp when scanned


@dataclass
class FolderStats:
    """Stats for an entire drive folder."""
    path: str
    total_charts: int = 0
    total_size: int = 0
    setlists: dict[str, SetlistStats] = field(default_factory=dict)
    scanned_at: float = 0.0    # Unix timestamp when scanned


class LocalStatsScanner:
    """
    Scans local filesystem for chart statistics.

    Provides accurate counts by detecting actual chart folders (those containing
    song.ini, notes.mid, or notes.chart files) rather than relying on manifest
    data which may be incomplete for nested archives.

    Results are cached with a configurable TTL (time-to-live).
    """

    def __init__(self, cache_ttl: int = 300):
        """
        Initialize scanner with cache settings.

        Args:
            cache_ttl: Cache time-to-live in seconds (default: 5 minutes)
        """
        self.cache_ttl = cache_ttl
        self._folder_cache: dict[str, FolderStats] = {}
        self._setlist_cache: dict[str, SetlistStats] = {}

    def get_folder_stats(
        self,
        folder_path: Path,
        disabled_setlists: Optional[set[str]] = None
    ) -> FolderStats:
        """
        Get stats for a folder, using cache if fresh.

        Args:
            folder_path: Path to the drive folder
            disabled_setlists: Set of setlist names to exclude from totals

        Returns:
            FolderStats with chart counts and sizes
        """
        cache_key = str(folder_path)
        now = time.time()

        # Check cache
        if cache_key in self._folder_cache:
            cached = self._folder_cache[cache_key]
            if now - cached.scanned_at < self.cache_ttl:
                # Apply disabled filter to cached results
                if disabled_setlists:
                    return self._filter_folder_stats(cached, disabled_setlists)
                return cached

        # Scan fresh
        stats = self._scan_folder(folder_path)
        self._folder_cache[cache_key] = stats

        if disabled_setlists:
            return self._filter_folder_stats(stats, disabled_setlists)
        return stats

    def get_setlist_stats(self, setlist_path: Path) -> SetlistStats:
        """
        Get stats for a single setlist folder.

        Args:
            setlist_path: Path to the setlist folder

        Returns:
            SetlistStats with chart count and size
        """
        cache_key = str(setlist_path)
        now = time.time()

        # Check cache
        if cache_key in self._setlist_cache:
            cached = self._setlist_cache[cache_key]
            if now - cached.scanned_at < self.cache_ttl:
                return cached

        # Scan fresh
        stats = self._scan_setlist(setlist_path)
        self._setlist_cache[cache_key] = stats
        return stats

    def clear_cache(self, folder_path: Optional[Path] = None):
        """
        Clear cache for specific folder or all.

        Args:
            folder_path: If provided, only clear cache for this folder.
                        If None, clear all cached data.
        """
        if folder_path is None:
            self._folder_cache.clear()
            self._setlist_cache.clear()
        else:
            path_str = str(folder_path)
            # Clear folder cache
            self._folder_cache.pop(path_str, None)
            # Clear setlist caches under this folder
            to_remove = [k for k in self._setlist_cache if k.startswith(path_str)]
            for k in to_remove:
                self._setlist_cache.pop(k, None)

    def is_cached(self, folder_path: Path) -> bool:
        """Check if folder stats are cached and fresh."""
        cache_key = str(folder_path)
        if cache_key not in self._folder_cache:
            return False
        cached = self._folder_cache[cache_key]
        return time.time() - cached.scanned_at < self.cache_ttl

    def _filter_folder_stats(
        self,
        stats: FolderStats,
        disabled_setlists: set[str]
    ) -> FolderStats:
        """Create filtered stats excluding disabled setlists."""
        filtered = FolderStats(
            path=stats.path,
            total_charts=stats.total_charts,
            total_size=stats.total_size,
            setlists={k: v for k, v in stats.setlists.items() if k not in disabled_setlists},
            scanned_at=stats.scanned_at
        )

        # Subtract disabled setlists from totals
        for name in disabled_setlists:
            if name in stats.setlists:
                filtered.total_charts -= stats.setlists[name].chart_count
                filtered.total_size -= stats.setlists[name].total_size

        filtered.total_charts = max(0, filtered.total_charts)
        filtered.total_size = max(0, filtered.total_size)
        return filtered

    def _scan_folder(self, folder_path: Path) -> FolderStats:
        """Scan a folder and all its setlists."""
        stats = FolderStats(
            path=str(folder_path),
            scanned_at=time.time()
        )

        if not folder_path.exists():
            return stats

        try:
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        setlist_stats = self._scan_setlist(Path(entry.path))
                        setlist_stats.name = entry.name
                        stats.setlists[entry.name] = setlist_stats
                        stats.total_charts += setlist_stats.chart_count
                        stats.total_size += setlist_stats.total_size
                        # Cache individual setlist
                        self._setlist_cache[entry.path] = setlist_stats
        except OSError:
            pass

        return stats

    def _scan_setlist(self, setlist_path: Path) -> SetlistStats:
        """Scan a single setlist folder for charts."""
        stats = SetlistStats(
            name=setlist_path.name,
            scanned_at=time.time()
        )

        if not setlist_path.exists():
            return stats

        chart_markers_lower = {m.lower() for m in CHART_MARKERS}

        def scan_for_charts(dir_path: Path) -> int:
            """
            Recursively scan for chart folders, including nested charts.

            Returns: size of non-chart content for parent to include.
            """
            try:
                has_marker = False
                subdirs = []
                direct_size = 0

                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if entry.is_file(follow_symlinks=False):
                            if entry.name.lower() in chart_markers_lower:
                                has_marker = True
                            try:
                                direct_size += entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                pass
                        elif entry.is_dir(follow_symlinks=False):
                            subdirs.append(Path(entry.path))

                # Recurse into all subdirs, collecting non-chart content size
                subdir_non_chart_size = 0
                for subdir in subdirs:
                    subdir_non_chart_size += scan_for_charts(subdir)

                if has_marker:
                    # This folder is a chart - include direct files + non-chart subdirs
                    stats.chart_count += 1
                    stats.total_size += direct_size + subdir_non_chart_size
                    return 0  # Chart content doesn't bubble up to parent
                else:
                    # Not a chart - return size for parent to potentially include
                    return direct_size + subdir_non_chart_size
            except OSError:
                return 0

        scan_for_charts(setlist_path)
        return stats


# Module-level scanner instance for convenience
_default_scanner: Optional[LocalStatsScanner] = None


def get_scanner(cache_ttl: int = 300) -> LocalStatsScanner:
    """Get or create the default scanner instance."""
    global _default_scanner
    if _default_scanner is None:
        _default_scanner = LocalStatsScanner(cache_ttl)
    return _default_scanner


def clear_local_stats_cache(folder_path: Optional[Path] = None):
    """
    Clear the local stats cache.

    Call this after downloads, purges, or any operation that modifies
    the local filesystem content.

    Args:
        folder_path: If provided, only clear cache for this folder.
                    If None, clear all cached data.
    """
    if _default_scanner is not None:
        _default_scanner.clear_cache(folder_path)


def scan_folder_charts(
    folder_path: Path,
    disabled_setlists: Optional[set[str]] = None
) -> tuple[int, int]:
    """
    Convenience function to scan a folder for chart counts.

    Args:
        folder_path: Path to scan
        disabled_setlists: Setlist names to exclude

    Returns:
        Tuple of (chart_count, total_size_bytes)
    """
    scanner = get_scanner()
    stats = scanner.get_folder_stats(folder_path, disabled_setlists)
    return stats.total_charts, stats.total_size


def scan_setlist_charts(setlist_path: Path) -> tuple[int, int]:
    """
    Convenience function to scan a setlist for chart counts.

    Args:
        setlist_path: Path to the setlist folder

    Returns:
        Tuple of (chart_count, total_size_bytes)
    """
    scanner = get_scanner()
    stats = scanner.get_setlist_stats(setlist_path)
    return stats.chart_count, stats.total_size
