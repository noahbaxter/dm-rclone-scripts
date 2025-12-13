"""
DM Chart Sync - Download charts from Google Drive without authentication.

This package provides classes for syncing files from Google Drive using
a pre-built manifest approach that eliminates API calls for end users.

Import from submodules directly:
    from src.config import UserSettings
    from src.manifest import Manifest
    from src.drive import DriveClient
    from src.sync import FolderSync
    from src.ui import show_main_menu
"""


def _get_version():
    """Read version from VERSION file."""
    from pathlib import Path
    from .core.paths import get_bundle_dir
    # Try relative to this file first (source), then bundle dir (PyInstaller)
    for base in [Path(__file__).parent.parent, get_bundle_dir()]:
        version_file = base / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
    return "0.0.0"


__version__ = _get_version()
