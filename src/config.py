"""
Configuration management for DM Chart Sync.

Config files:
- drives.json: Admin-maintained list of available drives (bundled with app)
- .dm-sync/settings.json: User preferences including which subfolders are enabled
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from .utils import sort_by_name


@dataclass
class DriveConfig:
    """A drive (root folder) configuration."""
    name: str
    folder_id: str
    description: str = ""
    group: str = ""  # Optional group name for categorization
    hidden: bool = False  # If True, hide from sync UI (still in manifest)

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "folder_id": self.folder_id,
            "description": self.description,
        }
        if self.group:
            d["group"] = self.group
        if self.hidden:
            d["hidden"] = self.hidden
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "DriveConfig":
        return cls(
            name=data.get("name", ""),
            folder_id=data.get("folder_id", ""),
            description=data.get("description", ""),
            group=data.get("group", ""),
            hidden=data.get("hidden", False),
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

    def get_visible_drives(self) -> list[DriveConfig]:
        """Get drives that are not hidden."""
        return [d for d in self.drives if not d.hidden]

    def get_groups(self, visible_only: bool = True) -> list[str]:
        """Get unique group names in order of first appearance."""
        seen = set()
        groups = []
        drives = self.get_visible_drives() if visible_only else self.drives
        for drive in drives:
            if drive.group and drive.group not in seen:
                seen.add(drive.group)
                groups.append(drive.group)
        return groups

    def get_drives_in_group(self, group: str, visible_only: bool = True) -> list[DriveConfig]:
        """Get all drives in a specific group."""
        drives = self.get_visible_drives() if visible_only else self.drives
        return [d for d in drives if d.group == group]

    def get_ungrouped_drives(self, visible_only: bool = True) -> list[DriveConfig]:
        """Get drives that don't belong to any group."""
        drives = self.get_visible_drives() if visible_only else self.drives
        return [d for d in drives if not d.group]


class UserSettings:
    """
    Manages .dm-sync/settings.json - user preferences that persist across runs.

    Stores:
    - Drive toggle states (which drives are enabled/disabled at the top level)
    - Subfolder toggle states (which subfolders are enabled/disabled per drive)
    """

    # Drives enabled by default when no settings file exists
    DEFAULT_ENABLED_DRIVES = {
        "1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf",  # BirdmanExe Drive
        "1bqsJzbXRkmRda3qJFX3W36UD3Sg_eIVj",  # Drummer's Monthly Drive
    }

    def __init__(self, path: Path):
        self.path = path
        # Drive-level toggles: { drive_folder_id: enabled_bool }
        self.drive_toggles: dict[str, bool] = {}
        # Subfolder toggles: { drive_folder_id: { subfolder_name: enabled_bool } }
        self.subfolder_toggles: dict[str, dict[str, bool]] = {}
        # Group expanded state: { group_name: expanded_bool }
        self.group_expanded: dict[str, bool] = {}
        # Whether to delete video files from extracted archive charts
        self.delete_videos: bool = True
        # Whether user has been prompted to sign in to Google
        self.oauth_prompted: bool = False
        # Track if this is a fresh settings file (no file existed)
        self._is_new: bool = False

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
                settings.group_expanded = data.get("group_expanded", {})
                settings.delete_videos = data.get("delete_videos", True)
                settings.oauth_prompted = data.get("oauth_prompted", False)
            except (json.JSONDecodeError, IOError):
                settings._is_new = True
        else:
            settings._is_new = True

        return settings

    def save(self):
        """Save user settings to file."""
        data = {
            "drive_toggles": self.drive_toggles,
            "subfolder_toggles": self.subfolder_toggles,
            "group_expanded": self.group_expanded,
            "delete_videos": self.delete_videos,
            "oauth_prompted": self.oauth_prompted,
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def is_drive_enabled(self, drive_id: str) -> bool:
        """Check if a drive is enabled at the top level.

        For new users (no settings file), only DEFAULT_ENABLED_DRIVES are enabled.
        For existing users, any drive not explicitly set defaults to enabled.
        """
        if drive_id in self.drive_toggles:
            return self.drive_toggles[drive_id]
        # New users: only default drives enabled
        if self._is_new:
            return drive_id in self.DEFAULT_ENABLED_DRIVES
        # Existing users: default to enabled for backwards compatibility
        return True

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

    def is_group_expanded(self, group_name: str) -> bool:
        """Check if a group is expanded (all groups default to expanded)."""
        if group_name not in self.group_expanded:
            # Default: all groups expanded
            return True
        return self.group_expanded.get(group_name, True)

    def toggle_group_expanded(self, group_name: str) -> bool:
        """Toggle a group's expanded state. Returns the new state."""
        current = self.is_group_expanded(group_name)
        self.group_expanded[group_name] = not current
        return not current


@dataclass
class CustomFolder:
    """A user-added custom Google Drive folder."""
    folder_id: str
    name: str
    last_scanned: str = ""  # ISO timestamp

    def to_dict(self) -> dict:
        return {
            "folder_id": self.folder_id,
            "name": self.name,
            "last_scanned": self.last_scanned,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CustomFolder":
        return cls(
            folder_id=data.get("folder_id", ""),
            name=data.get("name", ""),
            last_scanned=data.get("last_scanned", ""),
        )


class CustomFolders:
    """
    Manages custom user-added Google Drive folders.

    Stores folder metadata in .dm-sync/local_manifest.json.
    Files for each folder are stored in the same file using the Manifest format.
    """

    def __init__(self, path: Path):
        self.path = path
        self.folders: list[CustomFolder] = []
        # File data uses the same format as main manifest (folder_id -> files list)
        self._file_data: dict[str, list] = {}

    @classmethod
    def load(cls, path: Path) -> "CustomFolders":
        """Load custom folders from file."""
        custom = cls(path)

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                custom.folders = [
                    CustomFolder.from_dict(f) for f in data.get("folders", [])
                ]
                custom._file_data = data.get("file_data", {})
            except (json.JSONDecodeError, IOError):
                pass

        return custom

    def save(self):
        """Save custom folders to file."""
        data = {
            "folders": [f.to_dict() for f in self.folders],
            "file_data": self._file_data,
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def add_folder(self, folder_id: str, name: str) -> CustomFolder:
        """Add a new custom folder."""
        # Check if already exists
        for folder in self.folders:
            if folder.folder_id == folder_id:
                # Update name if different
                folder.name = name
                return folder

        folder = CustomFolder(folder_id=folder_id, name=name)
        self.folders.append(folder)
        return folder

    def remove_folder(self, folder_id: str):
        """Remove a custom folder and its file data."""
        self.folders = [f for f in self.folders if f.folder_id != folder_id]
        self._file_data.pop(folder_id, None)

    def get_folder(self, folder_id: str) -> Optional[CustomFolder]:
        """Get a custom folder by ID."""
        for folder in self.folders:
            if folder.folder_id == folder_id:
                return folder
        return None

    def has_folder(self, folder_id: str) -> bool:
        """Check if a folder ID is in custom folders."""
        return any(f.folder_id == folder_id for f in self.folders)

    def get_files(self, folder_id: str) -> list:
        """Get file list for a custom folder."""
        return self._file_data.get(folder_id, [])

    def set_files(self, folder_id: str, files: list, timestamp: str = ""):
        """Set file list for a custom folder."""
        self._file_data[folder_id] = files
        # Update last_scanned timestamp
        folder = self.get_folder(folder_id)
        if folder:
            from datetime import datetime, timezone
            folder.last_scanned = timestamp or datetime.now(timezone.utc).isoformat()

    def get_folder_ids(self) -> set[str]:
        """Get set of all custom folder IDs."""
        return {f.folder_id for f in self.folders}

    def to_drive_configs(self) -> list[DriveConfig]:
        """Convert custom folders to DriveConfig objects for menu display."""
        return [
            DriveConfig(
                name=f.name,
                folder_id=f.folder_id,
                description="Custom folder",
                group="Custom Folders",
            )
            for f in self.folders
        ]


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
