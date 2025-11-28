"""
DM Chart Sync - Download charts from Google Drive without authentication.

This package provides classes for syncing files from Google Drive using
a pre-built manifest approach that eliminates API calls for end users.
"""

# Core modules
from .manifest import Manifest
from .config import DrivesConfig, UserSettings, DriveConfig, extract_subfolders_from_manifest
from .utils import format_size, format_duration, print_progress, clear_screen

# Drive module
from .drive import DriveClient, FolderScanner, OAuthManager, ChangeTracker

# Sync module
from .sync import FileDownloader, FolderSync, purge_all_folders, get_sync_status, SyncStatus

# UI module
from .ui import print_header, show_main_menu, show_subfolder_settings, Colors, compute_main_menu_cache, show_confirmation

__all__ = [
    # Core
    "Manifest",
    "DrivesConfig",
    "UserSettings",
    "DriveConfig",
    "extract_subfolders_from_manifest",
    "format_size",
    "format_duration",
    "print_progress",
    "clear_screen",
    # Drive
    "DriveClient",
    "FolderScanner",
    "OAuthManager",
    "ChangeTracker",
    # Sync
    "FileDownloader",
    "FolderSync",
    "purge_all_folders",
    "get_sync_status",
    "SyncStatus",
    # UI
    "print_header",
    "show_main_menu",
    "show_subfolder_settings",
    "Colors",
    "compute_main_menu_cache",
    "show_confirmation",
]

__version__ = "2.0.0"
