"""
Remote manifest fetching for DM Chart Sync.
"""

import requests

from ..core.paths import get_manifest_path
from ..core.formatting import sanitize_path
from .manifest import Manifest

# Remote manifest URL (GitHub releases)
MANIFEST_URL = "https://github.com/noahbaxter/dm-rclone-scripts/releases/download/manifest/manifest.json"


def _sanitize_manifest_paths(manifest: dict) -> dict:
    """
    Sanitize all file paths in manifest for consistent comparison.

    This ensures paths are normalized (NFC Unicode, illegal chars replaced)
    at the source, so all downstream code gets clean paths automatically.
    """
    for folder in manifest.get("folders", []):
        for f in folder.get("files", []):
            if "path" in f:
                f["path"] = sanitize_path(f["path"])
    return manifest


def fetch_manifest(use_local: bool = False) -> dict:
    """
    Fetch folder manifest from remote URL or local file.

    Args:
        use_local: If True, only read from local manifest.json (skip remote)

    Returns:
        Manifest data as dict (with sanitized file paths)
    """
    local_path = get_manifest_path()

    if not use_local:
        # Try remote first
        try:
            response = requests.get(MANIFEST_URL, timeout=10)
            response.raise_for_status()
            return _sanitize_manifest_paths(response.json())
        except Exception:
            pass

    # Use local manifest
    if local_path.exists():
        manifest = Manifest.load(local_path)
        return _sanitize_manifest_paths(manifest.to_dict())

    print("Warning: Could not load folder manifest.\n")
    return {"folders": []}
