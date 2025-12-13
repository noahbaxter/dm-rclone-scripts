"""
Manifest management for DM Chart Sync.

The manifest is a JSON file containing the complete file tree with checksums,
eliminating the need for users to scan Google Drive.
"""

from .manifest import Manifest, FolderEntry, FileEntry
from .fetch import fetch_manifest, MANIFEST_URL
from .counter import (
    ChartType,
    ChartCounts,
    SubfolderStats,
    DriveStats,
    count_charts_in_files,
    is_sng_file,
    is_zip_file,
    has_folder_chart_markers,
    detect_chart_type_from_filenames,
)

__all__ = [
    # Core manifest
    "Manifest",
    "FolderEntry",
    "FileEntry",
    "fetch_manifest",
    "MANIFEST_URL",
    # Chart counting
    "ChartType",
    "ChartCounts",
    "SubfolderStats",
    "DriveStats",
    "count_charts_in_files",
    "is_sng_file",
    "is_zip_file",
    "has_folder_chart_markers",
    "detect_chart_type_from_filenames",
]
