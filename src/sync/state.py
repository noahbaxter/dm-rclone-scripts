"""
Sync state management for DM Chart Sync.

Stores sync metadata in a recursive tree structure that mirrors the folder hierarchy.
Archives are treated as folders with extra metadata (md5, archive_size, extracted_at).
"""

import json
from datetime import datetime
from pathlib import Path

from ..core.paths import get_sync_state_path, get_download_path


class SyncState:
    """
    Manages sync state stored in .dm-sync/sync_state.json

    Uses recursive tree structure mirroring folder hierarchy.
    Builds flat lookup caches on load for O(1) access.
    """

    VERSION = 1

    def __init__(self, sync_root: Path = None):
        # For production: use centralized paths from paths.py
        # For testing: pass sync_root to use temp directory
        if sync_root:
            self.sync_root = sync_root
            self.state_file = sync_root / "sync_state.json"
        else:
            self.sync_root = get_download_path()
            self.state_file = get_sync_state_path()
        self._data = None
        self._files = {}      # Flat cache: path -> file node
        self._archives = {}   # Flat cache: path -> archive node

    # --- Core I/O ---

    def load(self):
        """Load state from disk and build lookup caches."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = None

        if not self._data or self._data.get("version") != self.VERSION:
            self._data = {
                "version": self.VERSION,
                "last_sync": None,
                "root": {}
            }

        # Build flat caches
        self._files = {}
        self._archives = {}
        self._flatten(self._data.get("root", {}), "")

    def save(self):
        """Atomic write: write to .tmp file, then rename."""
        self._data["last_sync"] = datetime.now().isoformat()

        # Ensure directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first
        tmp_file = self.state_file.with_suffix(".json.tmp")
        with open(tmp_file, "w") as f:
            json.dump(self._data, f, indent=2)

        # Atomic rename
        tmp_file.replace(self.state_file)

    def _flatten(self, node: dict, path: str):
        """Recursively build flat lookup caches from tree."""
        for name, child in node.items():
            child_path = f"{path}/{name}" if path else name
            node_type = child.get("type")

            if node_type == "file":
                self._files[child_path] = child
            elif node_type == "archive":
                self._archives[child_path] = child
                # Recurse into archive contents
                # Use parent path (not archive path) since extracted files
                # are placed in the parent folder, not a wrapper folder
                self._flatten(child.get("children", {}), path)
            elif node_type == "folder":
                self._flatten(child.get("children", {}), child_path)

    def _rebuild_cache(self):
        """Rebuild flat caches after tree modification."""
        self._files = {}
        self._archives = {}
        self._flatten(self._data.get("root", {}), "")

    # --- Tree manipulation ---

    def _get_or_create_path(self, path: str, final_type: str = "folder") -> dict:
        """
        Navigate to path in tree, creating folders as needed.
        Returns the node at the path.
        """
        parts = path.split("/")
        current = self._data["root"]

        for i, part in enumerate(parts):
            if part not in current:
                # Last part gets the specified type, others are folders
                is_last = (i == len(parts) - 1)
                if is_last:
                    current[part] = {"type": final_type}
                    if final_type in ("folder", "archive"):
                        current[part]["children"] = {}
                else:
                    current[part] = {"type": "folder", "children": {}}

            node = current[part]
            if i < len(parts) - 1:
                # Not at final destination yet, descend into children
                current = node.get("children", {})
                if "children" not in node:
                    node["children"] = {}
                    current = node["children"]

        return current[parts[-1]]

    def _remove_path(self, path: str) -> bool:
        """Remove a node from the tree. Returns True if removed."""
        parts = path.split("/")
        current = self._data["root"]

        # Navigate to parent
        for part in parts[:-1]:
            if part not in current:
                return False
            node = current[part]
            current = node.get("children", {})

        # Remove the final part
        if parts[-1] in current:
            del current[parts[-1]]
            return True
        return False

    # --- File operations (O(1) via flat cache) ---

    def is_file_synced(self, path: str, expected_size: int) -> bool:
        """Check if file is tracked with matching size."""
        f = self._files.get(path)
        return f is not None and f.get("size") == expected_size

    def get_all_files(self) -> set:
        """Get all tracked file paths (for purge planning)."""
        return set(self._files.keys())

    def check_files_exist(self, paths: list = None, verify_sizes: bool = True) -> list:
        """
        Return list of tracked files that are missing or have wrong size.

        Args:
            paths: Optional list of paths to check. If None, checks all files.
            verify_sizes: If True, also verify disk size matches recorded size.
                         Files modified after download/extraction will be flagged.
        """
        if paths is None:
            paths = self._files.keys()

        missing = []
        for path in paths:
            full_path = self.sync_root / path
            if not full_path.exists():
                missing.append(path)
            elif verify_sizes:
                # Check size matches what we recorded
                recorded = self._files.get(path)
                if recorded:
                    expected_size = recorded.get("size", 0)
                    try:
                        actual_size = full_path.stat().st_size
                        if actual_size != expected_size:
                            missing.append(path)
                    except OSError:
                        missing.append(path)
        return missing

    # --- Archive operations (O(1) via flat cache) ---

    def is_archive_synced(self, path: str, expected_md5: str) -> bool:
        """Check if archive is synced with matching MD5."""
        a = self._archives.get(path)
        return a is not None and a.get("md5") == expected_md5

    def get_archive(self, path: str) -> dict:
        """Get archive node by path, or None if not found."""
        return self._archives.get(path)

    def get_archive_files(self, archive_path: str) -> list:
        """Get all file paths under this archive."""
        archive = self._archives.get(archive_path)
        if not archive:
            return []

        # Get parent path for building full paths
        if "/" in archive_path:
            parent_path = archive_path.rsplit("/", 1)[0]
        else:
            parent_path = ""

        # Walk the archive's children to collect file paths
        files = []
        self._collect_files_from_node(archive.get("children", {}), parent_path, files)
        return files

    def _collect_files_from_node(self, node: dict, parent_path: str, files: list):
        """Recursively collect file paths from a node."""
        for name, child in node.items():
            child_path = f"{parent_path}/{name}" if parent_path else name
            node_type = child.get("type")

            if node_type == "file":
                files.append(child_path)
            elif node_type == "folder":
                self._collect_files_from_node(child.get("children", {}), child_path, files)

    # --- Write operations (update tree + rebuild cache) ---

    def add_file(self, path: str, size: int, md5: str = None):
        """Add a directly-downloaded file to the tree."""
        node = self._get_or_create_path(path, final_type="file")
        node["size"] = size
        if md5:
            node["md5"] = md5
        node["synced_at"] = datetime.now().isoformat()
        self._rebuild_cache()

    def add_archive(self, path: str, md5: str, archive_size: int, files: dict):
        """
        Add an extracted archive to the tree.

        Args:
            path: Archive path (e.g., "DriveName/Setlist/archive.7z")
            md5: Archive MD5 hash
            archive_size: Size of the archive file
            files: Dict of {relative_path: size} for extracted files
        """
        # Create or update archive node
        node = self._get_or_create_path(path, final_type="archive")
        node["md5"] = md5
        node["archive_size"] = archive_size
        node["extracted_at"] = datetime.now().isoformat()
        node["children"] = {}

        # Add all extracted files under the archive
        for file_path, size in files.items():
            self._add_file_under_node(node, file_path, size)

        self._rebuild_cache()

    def _add_file_under_node(self, root_node: dict, path: str, size: int):
        """Add a file under a specific node (used for archive contents)."""
        parts = path.split("/")
        current = root_node.get("children", {})
        if "children" not in root_node:
            root_node["children"] = {}
            current = root_node["children"]

        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            if is_last:
                current[part] = {"type": "file", "size": size}
            else:
                if part not in current:
                    current[part] = {"type": "folder", "children": {}}
                current = current[part]["children"]

    def remove_archive(self, path: str):
        """Remove an archive and all its children from the tree."""
        if self._remove_path(path):
            self._rebuild_cache()

    def remove_file(self, path: str):
        """Remove a single file from the tree."""
        if self._remove_path(path):
            self._rebuild_cache()

    # --- Utility ---

    def get_stats(self) -> dict:
        """Get summary statistics."""
        return {
            "total_files": len(self._files),
            "total_archives": len(self._archives),
            "last_sync": self._data.get("last_sync"),
        }

    def cleanup_check_txt_files(self) -> int:
        """
        Delete all check.txt files from the sync root.

        Called on startup to clean up legacy checksum files now that we use sync_state.json.

        Returns:
            Number of check.txt files deleted
        """
        deleted = 0
        if not self.sync_root.exists():
            return deleted

        for check_file in self.sync_root.rglob("check.txt"):
            try:
                check_file.unlink()
                deleted += 1
            except OSError:
                pass

        return deleted
