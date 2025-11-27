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
]

__version__ = "2.0.0"
