"""
Configuration management for DM Chart Sync.

Two config files:
- drives.json: Admin-maintained list of available drives (top-level only)
- user_settings.json: User preferences including which subfolders are enabled
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class DriveConfig:
    """A drive (root folder) configuration."""
    name: str
    folder_id: str
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "folder_id": self.folder_id,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DriveConfig":
        return cls(
            name=data.get("name", ""),
            folder_id=data.get("folder_id", ""),
            description=data.get("description", ""),
        )


class DrivesConfig:
    """
    Manages drives.json - the admin-maintained list of drives.

    This file is shipped with the app and defines available drives.
    Subfolders are discovered automatically from the manifest.
    """

    def __init__(self, path: Path):
        self.path = path
        self.drives: list[DriveConfig] = []

    @classmethod
    def load(cls, path: Path) -> "DrivesConfig":
        """Load drives configuration from file."""
        config = cls(path)

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                for drive_data in data.get("drives", []):
                    config.drives.append(DriveConfig.from_dict(drive_data))
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load drives.json: {e}")

        return config

    def save(self):
        """Save drives configuration to file."""
        data = {
            "drives": [d.to_dict() for d in self.drives]
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def get_drive(self, folder_id: str) -> Optional[DriveConfig]:
        """Get drive by folder ID."""
        for drive in self.drives:
            if drive.folder_id == folder_id:
                return drive
        return None

    def to_root_folders_list(self) -> list[dict]:
        """Convert to the ROOT_FOLDERS format used by manifest_gen.py."""
        return [d.to_dict() for d in self.drives]


class UserSettings:
    """
    Manages user_settings.json - user preferences that persist across runs.

    Stores:
    - Drive toggle states (which drives are enabled/disabled at the top level)
    - Subfolder toggle states (which subfolders are enabled/disabled per drive)
    """

    def __init__(self, path: Path):
        self.path = path
        # Drive-level toggles: { drive_folder_id: enabled_bool }
        self.drive_toggles: dict[str, bool] = {}
        # Subfolder toggles: { drive_folder_id: { subfolder_name: enabled_bool } }
        self.subfolder_toggles: dict[str, dict[str, bool]] = {}

    @classmethod
    def load(cls, path: Path) -> "UserSettings":
        """Load user settings from file."""
        settings = cls(path)

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                settings.drive_toggles = data.get("drive_toggles", {})
                settings.subfolder_toggles = data.get("subfolder_toggles", {})
            except (json.JSONDecodeError, IOError):
                pass

        return settings

    def save(self):
        """Save user settings to file."""
        data = {
            "drive_toggles": self.drive_toggles,
            "subfolder_toggles": self.subfolder_toggles
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def is_drive_enabled(self, drive_id: str) -> bool:
        """Check if a drive is enabled at the top level (defaults to True)."""
        return self.drive_toggles.get(drive_id, True)

    def set_drive_enabled(self, drive_id: str, enabled: bool):
        """Set whether a drive is enabled at the top level."""
        self.drive_toggles[drive_id] = enabled

    def toggle_drive(self, drive_id: str) -> bool:
        """Toggle a drive's enabled state. Returns the new state."""
        current = self.is_drive_enabled(drive_id)
        self.set_drive_enabled(drive_id, not current)
        return not current

    def enable_drive(self, drive_id: str):
        """Enable a drive."""
        self.set_drive_enabled(drive_id, True)

    def is_subfolder_enabled(self, drive_id: str, subfolder_name: str) -> bool:
        """Check if a subfolder is enabled (defaults to True)."""
        return self.subfolder_toggles.get(drive_id, {}).get(subfolder_name, True)

    def set_subfolder_enabled(self, drive_id: str, subfolder_name: str, enabled: bool):
        """Set whether a subfolder is enabled."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        self.subfolder_toggles[drive_id][subfolder_name] = enabled

    def toggle_subfolder(self, drive_id: str, subfolder_name: str) -> bool:
        """Toggle a subfolder's enabled state. Returns the new state."""
        current = self.is_subfolder_enabled(drive_id, subfolder_name)
        self.set_subfolder_enabled(drive_id, subfolder_name, not current)
        return not current

    def get_disabled_subfolders(self, drive_id: str) -> set[str]:
        """Get set of disabled subfolder names for a drive."""
        toggles = self.subfolder_toggles.get(drive_id, {})
        return {name for name, enabled in toggles.items() if not enabled}

    def enable_all(self, drive_id: str, subfolder_names: list[str]):
        """Enable all subfolders for a drive."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        for name in subfolder_names:
            self.subfolder_toggles[drive_id][name] = True

    def disable_all(self, drive_id: str, subfolder_names: list[str]):
        """Disable all subfolders for a drive."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        for name in subfolder_names:
            self.subfolder_toggles[drive_id][name] = False


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

    return sorted(subfolders)
