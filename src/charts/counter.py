"""
Chart counting for manifest generation.

Counts charts (folder, zip, sng) within a file list, organized by top-level subfolder.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict

from .detector import (
    CHART_NOTE_FILES,
    CHART_INI_FILES,
    ZIP_EXTENSIONS,
    SNG_EXTENSION,
)
from .base import ChartType
from ..utils import sort_by_name


@dataclass
class ChartCounts:
    """Chart counts by type."""
    folder: int = 0
    zip: int = 0
    sng: int = 0

    @property
    def total(self) -> int:
        return self.folder + self.zip + self.sng

    def to_dict(self) -> dict:
        return {
            "folder": self.folder,
            "zip": self.zip,
            "sng": self.sng,
            "total": self.total,
        }

    def __add__(self, other: "ChartCounts") -> "ChartCounts":
        return ChartCounts(
            folder=self.folder + other.folder,
            zip=self.zip + other.zip,
            sng=self.sng + other.sng,
        )


@dataclass
class SubfolderStats:
    """Statistics for a top-level subfolder."""
    name: str
    file_count: int = 0
    total_size: int = 0
    chart_counts: ChartCounts = field(default_factory=ChartCounts)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "charts": self.chart_counts.to_dict(),
        }


@dataclass
class DriveStats:
    """Statistics for an entire drive."""
    file_count: int = 0
    total_size: int = 0
    chart_counts: ChartCounts = field(default_factory=ChartCounts)
    subfolders: Dict[str, SubfolderStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file_count": self.file_count,
            "total_size": self.total_size,
            "charts": self.chart_counts.to_dict(),
            "subfolders": [sf.to_dict() for sf in sort_by_name(list(self.subfolders.values()), key=lambda x: x.name)],
        }


def count_charts_in_files(files: List[dict]) -> DriveStats:
    """
    Count charts in a list of files, organized by top-level subfolder.

    A chart is identified as:
    - FOLDER: A directory containing song.ini AND (notes.mid or notes.chart)
    - ZIP: A .zip, .rar, or .7z file
    - SNG: A .sng file

    Args:
        files: List of file dicts with 'path', 'size' keys

    Returns:
        DriveStats with counts per subfolder and totals
    """
    stats = DriveStats()

    # Group files by top-level subfolder
    files_by_subfolder: Dict[str, List[dict]] = defaultdict(list)
    root_files: List[dict] = []

    for f in files:
        path = f.get("path", "")
        size = f.get("size", 0)
        parts = Path(path).parts

        stats.file_count += 1
        stats.total_size += size

        if len(parts) > 1:
            subfolder = parts[0]
            files_by_subfolder[subfolder].append(f)

            # Track subfolder stats
            if subfolder not in stats.subfolders:
                stats.subfolders[subfolder] = SubfolderStats(name=subfolder)
            stats.subfolders[subfolder].file_count += 1
            stats.subfolders[subfolder].total_size += size
        else:
            root_files.append(f)

    # Count charts in each subfolder
    for subfolder, subfolder_files in files_by_subfolder.items():
        counts = _count_charts_in_subfolder(subfolder_files, subfolder)
        stats.subfolders[subfolder].chart_counts = counts
        stats.chart_counts = stats.chart_counts + counts

    # Count charts in root (if any)
    if root_files:
        root_counts = _count_root_charts(root_files)
        stats.chart_counts = stats.chart_counts + root_counts

    return stats


def _count_charts_in_subfolder(files: List[dict], subfolder_name: str) -> ChartCounts:
    """
    Count charts within a subfolder's files.

    Charts can be at any depth within the subfolder. We identify charts by:
    - Folders containing song.ini or notes.mid/chart (folder charts)
    - .sng files (sng charts)
    - .zip/.rar/.7z files (zip charts)
    """
    counts = ChartCounts()

    # Group files by their parent folder (at any depth)
    # e.g., "Charter/Sub/Artist - Song/notes.mid" -> parent is "Charter/Sub/Artist - Song"
    files_by_parent: Dict[str, List[str]] = defaultdict(list)

    for f in files:
        path = f.get("path", "")
        parts = Path(path).parts

        if len(parts) < 2:
            continue

        # Get the parent folder path (everything except the filename)
        parent = "/".join(parts[:-1])
        filename = parts[-1].lower()
        files_by_parent[parent].append(filename)

    # Find chart folders at any depth
    chart_folders_found = set()

    for parent_path, filenames in files_by_parent.items():
        # Check for standalone zip/sng files
        for filename in filenames:
            if filename.endswith(SNG_EXTENSION):
                counts.sng += 1
            elif any(filename.endswith(ext) for ext in ZIP_EXTENSIONS):
                counts.zip += 1

        # Check if this folder is a chart folder (has song.ini or notes files)
        filenames_set = set(filenames)
        has_ini = bool(filenames_set & {f.lower() for f in CHART_INI_FILES})
        has_notes = bool(filenames_set & {f.lower() for f in CHART_NOTE_FILES})

        if has_ini or has_notes:
            chart_folders_found.add(parent_path)

    counts.folder = len(chart_folders_found)
    return counts


def _count_root_charts(files: List[dict]) -> ChartCounts:
    """Count charts from files at the root level (no subfolder)."""
    counts = ChartCounts()

    for f in files:
        path = f.get("path", "").lower()
        if path.endswith(SNG_EXTENSION):
            counts.sng += 1
        elif any(path.endswith(ext) for ext in ZIP_EXTENSIONS):
            counts.zip += 1

    return counts


def _detect_chart_type_from_filenames(filenames: List[str]) -> ChartType | None:
    """
    Detect chart type from a list of filenames in a folder.

    Args:
        filenames: List of lowercase filenames

    Returns:
        Detected ChartType, or None if not a chart
    """
    filenames_set = set(filenames)

    # Check for .sng files
    if any(f.endswith(SNG_EXTENSION) for f in filenames):
        return ChartType.SNG

    # Check for archive files
    if any(any(f.endswith(ext) for ext in ZIP_EXTENSIONS) for f in filenames):
        return ChartType.ZIP

    # Check for traditional folder chart markers (needs song.ini or notes file)
    has_ini = bool(filenames_set & {f.lower() for f in CHART_INI_FILES})
    has_notes = bool(filenames_set & {f.lower() for f in CHART_NOTE_FILES})

    if has_ini or has_notes:
        return ChartType.FOLDER

    # Not a chart folder
    return None
