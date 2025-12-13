"""
Custom folder management for DM Chart Sync.

Manages user-added Google Drive folders that aren't in the main manifest.
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from .drives import DriveConfig


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
