"""
DM Chart Sync - Download charts from Google Drive without authentication.

This package provides classes for syncing files from Google Drive using
a pre-built manifest approach that eliminates API calls for end users.
"""

from .drive_client import DriveClient
from .manifest import Manifest
from .config import UserConfig
from .downloader import FileDownloader
from .scanner import FolderScanner
from .auth import OAuthManager
from .changes import ChangeTracker
from .utils import format_size, format_duration, print_progress
from .sync_ops import FolderSync, purge_extra_files
from .keyboard import CancelInput, input_with_esc, wait_for_key, menu_input
from .charts import (
    Chart,
    ChartType,
    ChartState,
    ChartFile,
    FolderChart,
    ZipChart,
    SngChart,
    detect_chart_type,
    create_chart,
)
from .ui import (
    clear_screen,
    show_main_menu,
    show_purge_menu,
    add_custom_folder,
    remove_custom_folder,
    change_download_path,
)

__all__ = [
    "DriveClient",
    "Manifest",
    "UserConfig",
    "FileDownloader",
    "FolderScanner",
    "OAuthManager",
    "ChangeTracker",
    "format_size",
    "format_duration",
    "print_progress",
    "FolderSync",
    "purge_extra_files",
    "CancelInput",
    "input_with_esc",
    "wait_for_key",
    "menu_input",
    "Chart",
    "ChartType",
    "ChartState",
    "ChartFile",
    "FolderChart",
    "ZipChart",
    "SngChart",
    "detect_chart_type",
    "create_chart",
    "clear_screen",
    "show_main_menu",
    "show_purge_menu",
    "add_custom_folder",
    "remove_custom_folder",
    "change_download_path",
]

__version__ = "2.0.0"
