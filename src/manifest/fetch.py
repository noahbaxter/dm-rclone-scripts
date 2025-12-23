"""
Remote manifest fetching for DM Chart Sync.
"""

import requests

from ..core.paths import get_manifest_path
from ..core.formatting import sanitize_path
from ..ui.widgets import display
from .manifest import Manifest

# Remote manifest URL (GitHub releases)
MANIFEST_URL = "https://github.com/noahbaxter/dm-rclone-scripts/releases/download/manifest/manifest.json"


def _sanitize_manifest_paths(manifest: dict) -> dict:
    for folder in manifest.get("folders", []):
        for f in folder.get("files", []):
            if "path" in f:
                f["path"] = sanitize_path(f["path"])
    return manifest


def check_network(timeout: float = 3.0) -> tuple[bool, str | None]:
    """Check if we can reach GitHub. Returns (is_online, error_message)."""
    try:
        requests.head("https://github.com", timeout=timeout)
        return True, None
    except requests.ConnectionError:
        return False, "No internet connection"
    except requests.Timeout:
        return False, "Connection timed out"
    except Exception as e:
        return False, f"Network error: {e}"


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
        # Check network connectivity first
        is_online, network_error = check_network()

        if not is_online:
            display.error_offline(network_error)
            raise SystemExit(1)

        # Network is up, try to fetch manifest
        try:
            response = requests.get(MANIFEST_URL, timeout=10)
            response.raise_for_status()
            return _sanitize_manifest_paths(response.json())
        except requests.HTTPError as e:
            display.error_manifest_http(e.response.status_code)
        except requests.Timeout:
            display.error_manifest_timeout()
        except Exception as e:
            display.error_manifest_generic(str(e))

        # Fetch failed - exit since we can't get the manifest
        print("Please try again later.\n")
        raise SystemExit(1)

    # Explicitly requested local manifest
    if local_path.exists():
        manifest = Manifest.load(local_path)
        return _sanitize_manifest_paths(manifest.to_dict())

    display.error_no_local_manifest()
    return {"folders": []}
