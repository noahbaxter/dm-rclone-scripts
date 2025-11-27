"""
Manifest management for DM Chart Sync.

The manifest is a JSON file containing the complete file tree with checksums,
eliminating the need for users to scan Google Drive.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class FileEntry:
    """A single file in the manifest."""
    id: str
    path: str
    name: str
    size: int = 0
    md5: str = ""
    modified: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FileEntry":
        return cls(
            id=data.get("id", ""),
            path=data.get("path", ""),
            name=data.get("name", ""),
            size=data.get("size", 0),
            md5=data.get("md5", ""),
            modified=data.get("modified", ""),
        )


@dataclass
class FolderEntry:
    """A folder in the manifest."""
    name: str
    folder_id: str
    description: str = ""
    file_count: int = 0
    total_size: int = 0
    files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "folder_id": self.folder_id,
            "description": self.description,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "files": [f.to_dict() if isinstance(f, FileEntry) else f for f in self.files],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FolderEntry":
        return cls(
            name=data.get("name", ""),
            folder_id=data.get("folder_id", ""),
            description=data.get("description", ""),
            file_count=data.get("file_count", 0),
            total_size=data.get("total_size", 0),
            files=data.get("files", []),
        )


class Manifest:
    """
    Manages the file tree manifest.

    The manifest contains:
    - version: Manifest format version
    - generated: ISO timestamp of last generation
    - changes_token: Page token for Changes API (incremental updates)
    - folders: List of folder entries with their files
    """

    VERSION = "2.0.0"

    def __init__(self, path: Optional[Path] = None):
        """
        Initialize manifest.

        Args:
            path: Path to manifest.json file
        """
        self.path = path
        self.version = self.VERSION
        self.generated: Optional[str] = None
        self.changes_token: Optional[str] = None
        self.folders: list[FolderEntry] = []

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        """
        Load manifest from file.

        Args:
            path: Path to manifest.json

        Returns:
            Loaded Manifest instance
        """
        manifest = cls(path)

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                manifest.version = data.get("version", cls.VERSION)
                manifest.generated = data.get("generated")
                manifest.changes_token = data.get("changes_token")
                manifest.folders = [
                    FolderEntry.from_dict(f) for f in data.get("folders", [])
                ]
            except (json.JSONDecodeError, IOError):
                pass

        return manifest

    def save(self):
        """Save manifest to file."""
        if not self.path:
            raise ValueError("No path set for manifest")

        self.generated = datetime.now(timezone.utc).isoformat()

        data = {
            "version": self.version,
            "generated": self.generated,
            "changes_token": self.changes_token,
            "folders": [f.to_dict() for f in self.folders],
        }

        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def to_dict(self) -> dict:
        """Convert manifest to dictionary."""
        return {
            "version": self.version,
            "generated": self.generated,
            "changes_token": self.changes_token,
            "folders": [f.to_dict() for f in self.folders],
        }

    def get_folder(self, folder_id: str) -> Optional[FolderEntry]:
        """Get folder by ID."""
        for folder in self.folders:
            if folder.folder_id == folder_id:
                return folder
        return None

    def get_folder_ids(self) -> set:
        """Get set of all folder IDs in manifest."""
        return {f.folder_id for f in self.folders}

    def add_folder(self, folder: FolderEntry):
        """Add or replace a folder entry."""
        # Remove existing entry with same ID
        self.folders = [f for f in self.folders if f.folder_id != folder.folder_id]
        self.folders.append(folder)

    def remove_folder(self, folder_id: str):
        """Remove a folder by ID."""
        self.folders = [f for f in self.folders if f.folder_id != folder_id]

    @property
    def total_files(self) -> int:
        """Total file count across all folders."""
        return sum(f.file_count for f in self.folders)

    @property
    def total_size(self) -> int:
        """Total size in bytes across all folders."""
        return sum(f.total_size for f in self.folders)

    def get_file_by_id(self, file_id: str) -> tuple:
        """
        Find a file by ID.

        Returns:
            Tuple of (folder_index, file_index) or (None, None) if not found
        """
        for fi, folder in enumerate(self.folders):
            for fli, file_entry in enumerate(folder.files):
                fid = file_entry.get("id") if isinstance(file_entry, dict) else file_entry.id
                if fid == file_id:
                    return fi, fli
        return None, None

    def build_file_lookup(self) -> dict:
        """
        Build a lookup table of file_id -> (folder_index, file_index).

        Useful for efficient updates during incremental sync.
        """
        lookup = {}
        for fi, folder in enumerate(self.folders):
            for fli, file_entry in enumerate(folder.files):
                fid = file_entry.get("id") if isinstance(file_entry, dict) else file_entry.id
                lookup[fid] = (fi, fli)
        return lookup
