"""
DM Chart Sync - Download charts from Google Drive without authentication.

This package provides classes for syncing files from Google Drive using
a pre-built manifest approach that eliminates API calls for end users.
"""

# Core modules
from .manifest import Manifest, fetch_manifest
from .config import DrivesConfig, UserSettings, DriveConfig, CustomFolders, extract_subfolders_from_manifest
from .utils import format_size, format_duration, print_progress, clear_screen, set_terminal_size, TeeOutput
from .core.paths import (
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
    cleanup_tmp_dir,
)

# Drive module
from .drive import DriveClient, FolderScanner, OAuthManager, UserOAuthManager, AuthManager, ChangeTracker

# Sync module
from .sync import FileDownloader, FolderSync, purge_all_folders, get_sync_status, SyncStatus

# Stats module
from .stats import get_best_stats, LocalStatsScanner, ManifestOverrides, clear_local_stats_cache

# UI module
from .ui import print_header, show_main_menu, show_subfolder_settings, Colors, compute_main_menu_cache, show_confirmation, show_oauth_prompt, show_add_custom_folder

__all__ = [
    # Core
    "Manifest",
    "fetch_manifest",
    "DrivesConfig",
    "UserSettings",
    "DriveConfig",
    "CustomFolders",
    "extract_subfolders_from_manifest",
    "format_size",
    "format_duration",
    "print_progress",
    "clear_screen",
    "set_terminal_size",
    "TeeOutput",
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
    "cleanup_tmp_dir",
    # Drive
    "DriveClient",
    "FolderScanner",
    "OAuthManager",
    "UserOAuthManager",
    "AuthManager",
    "ChangeTracker",
    # Sync
    "FileDownloader",
    "FolderSync",
    "purge_all_folders",
    "get_sync_status",
    "SyncStatus",
    # Stats
    "get_best_stats",
    "LocalStatsScanner",
    "ManifestOverrides",
    "clear_local_stats_cache",
    # UI
    "print_header",
    "show_main_menu",
    "show_subfolder_settings",
    "Colors",
    "compute_main_menu_cache",
    "show_confirmation",
    "show_oauth_prompt",
    "show_add_custom_folder",
]

def _get_version():
    """Read version from VERSION file."""
    from pathlib import Path
    # Try relative to this file first (source), then bundle dir (PyInstaller)
    for base in [Path(__file__).parent.parent, get_bundle_dir()]:
        version_file = base / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
    return "0.0.0"

__version__ = _get_version()
