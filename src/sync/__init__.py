"""
Sync operations module.

Handles file downloading, sync logic, and progress tracking.
"""

from .progress import ProgressTracker
from .cache import clear_cache, clear_folder_cache
from .checksum import read_checksum, write_checksum, repair_checksum_sizes
from .sync_status import SyncStatus, get_sync_status
from .download_planner import DownloadTask, plan_downloads
from .purge_planner import PurgeStats, count_purgeable_files, count_purgeable_detailed
from .purger import delete_files
from .folder_sync import FolderSync, purge_all_folders, repair_all_checksums
from .downloader import FileDownloader, DownloadResult

# Backwards compatibility aliases
clear_scan_cache = clear_cache

__all__ = [
    # Progress
    "ProgressTracker",
    # Cache
    "clear_cache",
    "clear_folder_cache",
    "clear_scan_cache",  # Backwards compat
    # Checksum
    "read_checksum",
    "write_checksum",
    "repair_checksum_sizes",
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
    "repair_all_checksums",
    # Downloader
    "FileDownloader",
    "DownloadResult",
]
