"""
Drive configuration management for DM Chart Sync.

Manages drives.json - the admin-maintained list of available drives.
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
