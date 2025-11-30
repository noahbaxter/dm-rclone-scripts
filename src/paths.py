"""
Centralized path management for DM Chart Sync.

All app data is stored in .dm-sync/ folder next to the executable.
This makes the app portable - everything stays together.

Directory structure:
    path/to/dm-sync.exe (or sync.py)
    path/to/.dm-sync/
        settings.json       - User preferences (drive toggles, etc.)
        token.json          - User OAuth token (optional sign-in)
        manifest.json       - Cached manifest from GitHub
        local_manifest.json - Custom drives added by user (future)
    path/to/Sync Charts/    - Downloaded chart files
"""

import sys
from pathlib import Path


# Directory name for app data (hidden on Unix)
DATA_DIR_NAME = ".dm-sync"

# Default folder name for downloaded charts
DOWNLOAD_FOLDER_NAME = "Sync Charts"


def get_app_dir() -> Path:
    """
    Get the directory where the app is located.

    For frozen (PyInstaller): directory containing the executable
    For development: directory containing sync.py (repo root)
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # Development: repo root (parent of src/)
    return Path(__file__).parent.parent


def get_bundle_dir() -> Path:
    """
    Get the directory where bundled resources are located.

    For PyInstaller builds, bundled files are extracted to a temp directory.
    For development, this is the same as get_app_dir().
    """
    if getattr(sys, "frozen", False):
        # PyInstaller extracts bundled files to _MEIPASS temp directory
        return Path(sys._MEIPASS)
    return get_app_dir()


def get_data_dir() -> Path:
    """
    Get the .dm-sync/ data directory, creating it if needed.

    All user-writable app data goes here.
    """
    data_dir = get_app_dir() / DATA_DIR_NAME
    data_dir.mkdir(exist_ok=True)
    return data_dir


def get_settings_path() -> Path:
    """Get path to user settings file."""
    return get_data_dir() / "settings.json"


def get_token_path() -> Path:
    """Get path to user OAuth token file."""
    return get_data_dir() / "token.json"


def get_manifest_path() -> Path:
    """Get path to cached manifest file."""
    return get_data_dir() / "manifest.json"


def get_local_manifest_path() -> Path:
    """Get path to local/custom drives manifest file."""
    return get_data_dir() / "local_manifest.json"


def get_download_path() -> Path:
    """Get the download directory for chart files."""
    return get_app_dir() / DOWNLOAD_FOLDER_NAME


def get_drives_config_path() -> Path:
    """Get path to drives config file (bundled with app)."""
    return get_bundle_dir() / "drives.json"


# Legacy paths (for migration)
def _get_legacy_settings_path() -> Path:
    """Old location: user_settings.json at app root."""
    return get_app_dir() / "user_settings.json"


def _get_legacy_token_path() -> Path:
    """Old location: user_token.json at app root."""
    return get_app_dir() / "user_token.json"


def _get_legacy_manifest_path() -> Path:
    """Old location: manifest.json at app root."""
    return get_app_dir() / "manifest.json"


def migrate_legacy_files() -> list[str]:
    """
    Migrate files from old locations to new .dm-sync/ directory.

    Returns:
        List of files that were migrated (for logging).
    """
    migrated = []

    # Ensure data dir exists
    data_dir = get_data_dir()

    # Migration mappings: (old_path, new_path)
    migrations = [
        (_get_legacy_settings_path(), get_settings_path(), "user_settings.json"),
        (_get_legacy_token_path(), get_token_path(), "user_token.json"),
        (_get_legacy_manifest_path(), get_manifest_path(), "manifest.json"),
    ]

    for old_path, new_path, name in migrations:
        if old_path.exists() and not new_path.exists():
            try:
                # Move file to new location
                old_path.rename(new_path)
                migrated.append(name)
            except Exception as e:
                # If rename fails (cross-device), try copy + delete
                try:
                    import shutil
                    shutil.copy2(old_path, new_path)
                    old_path.unlink()
                    migrated.append(name)
                except Exception:
                    # Migration failed, leave old file in place
                    pass

    return migrated
