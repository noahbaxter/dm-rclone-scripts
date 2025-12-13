"""
Sync operations module.

Handles file downloading, sync logic, and progress tracking.
"""

from ..core.progress import ProgressTracker  # Re-export from core for backwards compat
from .cache import clear_cache, clear_folder_cache, FolderStats, FolderStatsCache
from .status import SyncStatus, get_sync_status
from .download_planner import DownloadTask, plan_downloads
from .purge_planner import PurgeStats, count_purgeable_files, count_purgeable_detailed
from .purger import delete_files
from .folder_sync import FolderSync, purge_all_folders
from .downloader import FileDownloader, DownloadResult
from .state import SyncState

# Backwards compatibility aliases
clear_scan_cache = clear_cache

__all__ = [
    # Progress
    "ProgressTracker",
    # Cache
    "clear_cache",
    "clear_folder_cache",
    "clear_scan_cache",  # Backwards compat
    "FolderStats",
    "FolderStatsCache",
    # Sync status
    "SyncStatus",
    "get_sync_status",
    # Download planning
    "DownloadTask",
    "plan_downloads",
    # Purge planning
    "PurgeStats",
    "count_purgeable_files",
    "count_purgeable_detailed",
    # Purger
    "delete_files",
    # Folder sync
    "FolderSync",
    "purge_all_folders",
    # Downloader
    "FileDownloader",
    "DownloadResult",
    # Sync state
    "SyncState",
]
