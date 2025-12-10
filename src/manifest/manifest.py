"""
Manifest classes for DM Chart Sync.

The manifest is a JSON file containing the complete file tree with checksums,
eliminating the need for users to scan Google Drive.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from ..core.formatting import name_sort_key, format_size


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
        from dataclasses import asdict
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
    # Chart statistics
    chart_count: int = 0
    charts: dict = field(default_factory=dict)  # {"folder": N, "zip": N, "sng": N, "total": N}
    subfolders: list = field(default_factory=list)  # List of subfolder stats
    # Completion status (False if scan was interrupted)
    complete: bool = True

    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "folder_id": self.folder_id,
            "description": self.description,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "files": [f.to_dict() if isinstance(f, FileEntry) else f for f in self.files],
            "complete": self.complete,
        }
        # Include chart stats if present
        if self.chart_count > 0 or self.charts:
            result["chart_count"] = self.chart_count
            result["charts"] = self.charts
        if self.subfolders:
            result["subfolders"] = self.subfolders
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "FolderEntry":
        return cls(
            name=data.get("name", ""),
            folder_id=data.get("folder_id", ""),
            description=data.get("description", ""),
            file_count=data.get("file_count", 0),
            total_size=data.get("total_size", 0),
            files=data.get("files", []),
            chart_count=data.get("chart_count", 0),
            charts=data.get("charts", {}),
            subfolders=data.get("subfolders", []),
            complete=data.get("complete", True),  # Default True for backwards compat
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

    def get_complete_folder_ids(self) -> set:
        """Get set of folder IDs that have been fully scanned."""
        # Treat drives with 0 files as incomplete (likely permission issue)
        return {f.folder_id for f in self.folders if f.complete and f.file_count > 0}

    def get_incomplete_folder_ids(self) -> set:
        """Get set of folder IDs that were partially scanned."""
        return {f.folder_id for f in self.folders if not f.complete}

    def all_complete(self) -> bool:
        """Check if all folders in manifest are fully scanned."""
        return all(f.complete for f in self.folders)

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

    def print_tree(self, sort_by: str = "charts"):
        """
        Print a tree view of manifest contents.

        Args:
            sort_by: Sort order - "charts", "size", or "name"
        """
        try:
            from ..ui.colors import Colors
        except ImportError:
            from colors import Colors

        def get_sort_key(item, is_folder=False):
            if is_folder:
                charts = item.charts or {}
                chart_count = charts.get("total", item.chart_count)
                size = item.total_size
                name = item.name
            else:
                chart_count = item.get("charts", {}).get("total", 0)
                size = item.get("total_size", 0)
                name = item.get("name", "")

            if sort_by == "size":
                return (-size, name_sort_key(name))
            elif sort_by == "name":
                return (name_sort_key(name),)
            else:  # charts (default)
                return (-chart_count, name_sort_key(name))

        total_charts = 0
        total_size = 0

        sorted_folders = sorted(self.folders, key=lambda f: get_sort_key(f, is_folder=True))

        for folder in sorted_folders:
            charts = folder.charts or {}
            chart_count = charts.get("total", folder.chart_count)
            total_charts += chart_count
            total_size += folder.total_size

            status = f" {Colors.DIM}[incomplete]{Colors.RESET}" if not folder.complete else ""
            print(f"{Colors.PURPLE}▐{Colors.RESET} {Colors.BOLD}{folder.name}{Colors.RESET} ({chart_count} charts, {format_size(folder.total_size)}){status}")

            if folder.subfolders:
                sorted_subs = sorted(folder.subfolders, key=lambda x: get_sort_key(x))
                for sf in sorted_subs:
                    sf_charts = sf.get("charts", {}).get("total", 0)
                    sf_size = sf.get("total_size", 0)
                    print(f"  {sf.get('name', '?')} {Colors.MUTED}({sf_charts} charts, {format_size(sf_size)}){Colors.RESET}")

        print()
        print(f"Total: {total_charts} charts, {format_size(total_size)}")
