"""
Chart abstraction module for DM Chart Sync.

Supports different chart formats:
- FolderChart: Loose files in a folder (song.ini, notes.mid, audio files)
- ZipChart: Compressed archive containing chart files
- SngChart: Single .sng container file

Each chart type handles its own download, comparison, and update logic.
"""

from .base import Chart, ChartType, ChartFile, ChartState
from .folder_chart import FolderChart
from .zip_chart import ZipChart
from .sng_chart import SngChart
from .detector import detect_chart_type, create_chart, create_charts_from_manifest
from .syncer import ChartSyncer, ChartProgress
from .counter import count_charts_in_files, ChartCounts, SubfolderStats, DriveStats
from .archive_inspect import get_archive_size_without_videos

__all__ = [
    "Chart",
    "ChartType",
    "ChartFile",
    "ChartState",
    "FolderChart",
    "ZipChart",
    "SngChart",
    "detect_chart_type",
    "create_chart",
    "create_charts_from_manifest",
    "ChartSyncer",
    "ChartProgress",
    "count_charts_in_files",
    "ChartCounts",
    "SubfolderStats",
    "DriveStats",
    "get_archive_size_without_videos",
]
