"""
Configuration management for DM Chart Sync.

Config files:
- drives.json: Admin-maintained list of available drives (bundled with app)
- .dm-sync/settings.json: User preferences including which subfolders are enabled
"""

from .drives import DriveConfig, DrivesConfig
from .settings import UserSettings
from .custom import CustomFolder, CustomFolders

from ..core.formatting import sort_by_name


def extract_subfolders_from_manifest(folder: dict) -> list[str]:
    """
    Extract unique top-level subfolder names from a manifest folder's files.

    Args:
        folder: A folder dict from the manifest with a "files" list

    Returns:
        Sorted list of unique top-level subfolder names
    """
    files = folder.get("files", [])
    if not files:
        return []

    subfolders = set()
    for f in files:
        path = f.get("path", "")
        if "/" in path:
            # Get the first path component (top-level subfolder)
            top_folder = path.split("/")[0]
            subfolders.add(top_folder)

    return sort_by_name(list(subfolders))


__all__ = [
    "DriveConfig",
    "DrivesConfig",
    "UserSettings",
    "CustomFolder",
    "CustomFolders",
    "extract_subfolders_from_manifest",
]
