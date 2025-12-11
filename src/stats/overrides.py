"""
Admin override management for manifest data.

This module allows forcing correct values for drives/setlists where manifest
data is known to be incomplete (e.g., nested archives where the manifest
only counts the archive file, not the charts inside).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SetlistOverride:
    """Override values for a setlist (chart count only, size comes from local scan or manifest)."""
    chart_count: Optional[int] = None


@dataclass
class FolderOverride:
    """Override values for a folder/drive."""
    folder_id: Optional[str] = None
    description: Optional[str] = None
    setlists: dict[str, SetlistOverride] = field(default_factory=dict)


class ManifestOverrides:
    """
    Manages admin overrides for manifest data.

    These overrides are used when:
    1. Local disk scan returns 0 (content not downloaded)
    2. The manifest has incorrect data (e.g., nested archives)

    Priority: Local scan > Admin override > Manifest
    """

    def __init__(self, path: Optional[Path] = None):
        """
        Initialize overrides manager.

        Args:
            path: Path to manifest_overrides.json file
        """
        self.path = path
        self.overrides: dict[str, FolderOverride] = {}
        self._loaded = False

    @classmethod
    def load(cls, path: Path) -> "ManifestOverrides":
        """
        Load overrides from JSON file.

        Args:
            path: Path to the JSON file

        Returns:
            ManifestOverrides instance with loaded data
        """
        instance = cls(path)
        instance._load_file()
        return instance

    def _load_file(self):
        """Load overrides from the JSON file."""
        if self.path is None or not self.path.exists():
            self._loaded = True
            return

        try:
            with open(self.path) as f:
                data = json.load(f)

            overrides_data = data.get("overrides", {})
            for folder_name, folder_data in overrides_data.items():
                folder_override = FolderOverride(
                    folder_id=folder_data.get("_folder_id"),
                    description=folder_data.get("_description")
                )

                setlists_data = folder_data.get("setlists", {})
                for setlist_name, setlist_data in setlists_data.items():
                    folder_override.setlists[setlist_name] = SetlistOverride(
                        chart_count=setlist_data.get("chart_count")
                    )

                self.overrides[folder_name] = folder_override

            self._loaded = True
        except (json.JSONDecodeError, OSError) as e:
            # Log error but don't crash - overrides are optional
            self._loaded = True

    def get_folder_override(self, folder_name: str) -> Optional[FolderOverride]:
        """
        Get overrides for a folder by name.

        Args:
            folder_name: Name of the drive folder

        Returns:
            FolderOverride if exists, None otherwise
        """
        if not self._loaded:
            self._load_file()
        return self.overrides.get(folder_name)

    def get_setlist_override(
        self,
        folder_name: str,
        setlist_name: str
    ) -> Optional[SetlistOverride]:
        """
        Get override for a specific setlist.

        Args:
            folder_name: Name of the drive folder
            setlist_name: Name of the setlist

        Returns:
            SetlistOverride if exists, None otherwise
        """
        folder = self.get_folder_override(folder_name)
        if folder is None:
            return None
        return folder.setlists.get(setlist_name)

    def get_chart_count(
        self,
        folder_name: str,
        setlist_name: str,
        default: int = 0
    ) -> int:
        """
        Get chart count, using override if exists, else default.

        Args:
            folder_name: Name of the drive folder
            setlist_name: Name of the setlist
            default: Default value if no override

        Returns:
            Chart count from override or default
        """
        override = self.get_setlist_override(folder_name, setlist_name)
        if override and override.chart_count is not None:
            return override.chart_count
        return default

    def has_override(self, folder_name: str, setlist_name: str) -> bool:
        """Check if an override exists for this folder/setlist combination."""
        override = self.get_setlist_override(folder_name, setlist_name)
        return override is not None


# Module-level instance for convenience
_default_overrides: Optional[ManifestOverrides] = None


def get_overrides(path: Optional[Path] = None) -> ManifestOverrides:
    """
    Get or create the default overrides instance.

    Args:
        path: Path to overrides file. If None, uses default location.

    Returns:
        ManifestOverrides instance
    """
    global _default_overrides
    if _default_overrides is None:
        if path is None:
            # Try default locations: bundle dir (PyInstaller) or source dir
            from ..core.paths import get_bundle_dir
            default_path = get_bundle_dir() / "manifest_overrides.json"
            path = default_path if default_path.exists() else None
        _default_overrides = ManifestOverrides.load(path) if path else ManifestOverrides()
    return _default_overrides


def reload_overrides(path: Optional[Path] = None):
    """Force reload of overrides from file."""
    global _default_overrides
    _default_overrides = None
    get_overrides(path)
