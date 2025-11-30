"""
DM Chart Sync - Download charts from Google Drive without authentication.

This package provides classes for syncing files from Google Drive using
a pre-built manifest approach that eliminates API calls for end users.
"""

# Core modules
from .manifest import Manifest
from .config import DrivesConfig, UserSettings, DriveConfig, extract_subfolders_from_manifest
from .utils import format_size, format_duration, print_progress, clear_screen
from .paths import (
    get_app_dir,
    get_bundle_dir,
    get_data_dir,
    get_settings_path,
    get_token_path,
    get_manifest_path,
    get_local_manifest_path,
    get_download_path,
    get_drives_config_path,
    migrate_legacy_files,
)

# Drive module
from .drive import DriveClient, FolderScanner, OAuthManager, UserOAuthManager, ChangeTracker

# Sync module
from .sync import FileDownloader, FolderSync, purge_all_folders, get_sync_status, SyncStatus

# UI module
from .ui import print_header, show_main_menu, show_subfolder_settings, Colors, compute_main_menu_cache, show_confirmation, show_oauth_prompt

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
    # Paths
    "get_app_dir",
    "get_bundle_dir",
    "get_data_dir",
    "get_settings_path",
    "get_token_path",
    "get_manifest_path",
    "get_local_manifest_path",
    "get_download_path",
    "get_drives_config_path",
    "migrate_legacy_files",
    # Drive
    "DriveClient",
    "FolderScanner",
    "OAuthManager",
    "UserOAuthManager",
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
    "show_oauth_prompt",
]

__version__ = "2.0.0"
