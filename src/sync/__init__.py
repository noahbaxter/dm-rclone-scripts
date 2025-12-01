"""
Sync operations module.

Handles file downloading, sync logic, and progress tracking.
"""

from .progress import ProgressTracker
from .downloader import FileDownloader, DownloadTask, DownloadResult, FolderProgress
from .operations import FolderSync, get_sync_status, SyncStatus, purge_all_folders, count_purgeable_charts, clear_scan_cache

__all__ = [
    "ProgressTracker",
    "FileDownloader",
    "DownloadTask",
    "DownloadResult",
    "FolderProgress",
    "FolderSync",
    "get_sync_status",
    "SyncStatus",
    "purge_all_folders",
    "count_purgeable_charts",
    "clear_scan_cache",
]
