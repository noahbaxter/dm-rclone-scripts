"""
DM Chart Sync - Download charts from Google Drive without authentication.

This package provides classes for syncing files from Google Drive using
a pre-built manifest approach that eliminates API calls for end users.
"""

from .drive_client import DriveClient
from .manifest import Manifest
from .downloader import FileDownloader
from .utils import format_size, format_duration, print_progress
from .sync_ops import FolderSync, purge_extra_files
from .ui import (
    clear_screen,
    print_header,
    show_main_menu,
    show_purge_menu,
)

__all__ = [
    "DriveClient",
    "Manifest",
    "FileDownloader",
    "format_size",
    "format_duration",
    "print_progress",
    "FolderSync",
    "purge_extra_files",
    "clear_screen",
    "print_header",
    "show_main_menu",
    "show_purge_menu",
]

__version__ = "2.0.0"
