"""Shared helpers for debug scripts."""

import sys
from pathlib import Path

# Add repo root to path for src imports
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from src - single source of truth
from src.manifest import MANIFEST_URL, fetch_manifest as _src_fetch_manifest


def fetch_manifest() -> dict:
    """Fetch manifest from GitHub releases (wrapper around src/manifest.py)."""
    print(f"Fetching manifest from GitHub releases...")
    return _src_fetch_manifest(use_local=False)


def find_folder_in_manifest(manifest: dict, folder_name: str) -> dict:
    """Find a folder in the manifest by name."""
    matching = [f for f in manifest.get("folders", []) if f.get("name") == folder_name]
    if not matching:
        available = [f.get("name") for f in manifest.get("folders", [])]
        raise ValueError(f"Folder '{folder_name}' not found. Available: {available}")
    return matching[0]


def load_settings_from_sync_path(sync_path: Path):
    """Load UserSettings from the .dm-sync folder relative to sync path."""
    from src.config import UserSettings

    # sync_path is like /path/to/Sync Charts/Guitar Hero
    # settings are at /path/to/Sync Charts/../.dm-sync/settings.json
    # or /path/to/.dm-sync/settings.json (parent of Sync Charts)
    settings_path = sync_path.parent.parent / ".dm-sync" / "settings.json"

    if not settings_path.exists():
        # Try one level up
        settings_path = sync_path.parent / ".dm-sync" / "settings.json"

    if not settings_path.exists():
        raise FileNotFoundError(f"No settings.json found near {sync_path}")

    print(f"Loading settings from: {settings_path}")
    return UserSettings.load(settings_path)  # Use .load() classmethod!
