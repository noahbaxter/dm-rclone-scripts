"""
DM Chart Sync - Download charts from Google Drive without authentication.

This package provides classes for syncing files from Google Drive using
a pre-built manifest approach that eliminates API calls for end users.
"""

from .drive_client import DriveClient
from .manifest import Manifest
from .downloader import FileDownloader
from .scanner import FolderScanner
from .utils import format_size, format_duration, print_progress, clear_screen
from .sync_ops import FolderSync, purge_all_folders, get_sync_status, SyncStatus
from .menu import print_header
from .ui import show_main_menu, show_subfolder_settings
from .config import DrivesConfig, UserSettings, DriveConfig, extract_subfolders_from_manifest
from .auth import OAuthManager
from .changes import ChangeTracker
from .colors import Colors

__all__ = [
    "DriveClient",
    "Manifest",
    "FileDownloader",
    "FolderScanner",
    "format_size",
    "format_duration",
    "print_progress",
    "FolderSync",
    "purge_all_folders",
    "clear_screen",
    "print_header",
    "show_main_menu",
    "show_subfolder_settings",
    "DrivesConfig",
    "UserSettings",
    "DriveConfig",
    "extract_subfolders_from_manifest",
    "OAuthManager",
    "ChangeTracker",
    "Colors",
    "get_sync_status",
    "SyncStatus",
]

__version__ = "2.0.0"
