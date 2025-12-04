"""
Change tracking for DM Chart Sync.

Uses Google Drive Changes API for incremental manifest updates.
"""

from typing import Optional, Set
from dataclasses import dataclass

from .client import DriveClient
from ..manifest import Manifest, FolderEntry


@dataclass
class ChangeStats:
    """Statistics from processing changes."""
    added: int = 0
    modified: int = 0
    removed: int = 0
    skipped: int = 0
    api_calls: int = 0


class ChangeTracker:
    """
    Tracks changes using Google Drive Changes API.

    This enables incremental manifest updates by only fetching
    what changed since the last sync, dramatically reducing API calls.
    """

    FOLDER_MIME = "application/vnd.google-apps.folder"
    SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

    def __init__(self, client: DriveClient, manifest: Manifest):
        """
        Initialize change tracker.

        Args:
            client: DriveClient with OAuth token
            manifest: Manifest to update
        """
        self.client = client
        self.manifest = manifest

    def get_start_token(self) -> str:
        """
        Get a new start token for tracking changes.

        Returns:
            Page token for use with apply_changes()
        """
        return self.client.get_changes_start_token()

    def apply_changes(
        self,
        tracked_folder_ids: Set[str],
        progress_callback=None,
    ) -> ChangeStats:
        """
        Apply changes since the last saved token.

        Args:
            tracked_folder_ids: Set of root folder IDs we're tracking
            progress_callback: Optional callback(stats) for progress updates

        Returns:
            ChangeStats with counts of changes made
        """
        saved_token = self.manifest.changes_token
        if not saved_token:
            raise ValueError("No saved token - run full scan first")

        start_api_calls = self.client.api_calls
        stats = ChangeStats()

        # Fetch changes
        changes, new_token = self.client.get_changes(saved_token)

        if not changes:
            self.manifest.changes_token = new_token
            stats.api_calls = self.client.api_calls - start_api_calls
            return stats

        # Build lookup for existing files
        file_lookup = self.manifest.build_file_lookup()
        files_to_remove = []

        for change in changes:
            file_id = change.get("fileId")
            is_removed = change.get("removed", False)
            file_data = change.get("file")

            # Handle removals and trashed files
            if is_removed or (file_data and file_data.get("trashed")):
                if file_id in file_lookup:
                    files_to_remove.append(file_lookup[file_id])
                    stats.removed += 1
                continue

            # Skip folders
            if file_data and file_data.get("mimeType") == self.FOLDER_MIME:
                continue

            # Handle shortcuts - need to fetch target's metadata for size/md5
            if file_data and file_data.get("mimeType") == self.SHORTCUT_MIME:
                shortcut_details = file_data.get("shortcutDetails", {})
                target_id = shortcut_details.get("targetId")
                target_mime = shortcut_details.get("targetMimeType", "")

                # Skip shortcuts to folders
                if target_mime == self.FOLDER_MIME:
                    continue

                # For shortcuts to files, fetch the target's metadata
                if target_id:
                    target_meta = self.client.get_file_metadata(
                        target_id,
                        fields="id,name,size,md5Checksum,modifiedTime,parents"
                    )
                    if target_meta:
                        # Use target's metadata but keep shortcut's file_id for tracking
                        # and merge parents so path resolution works
                        file_data = {
                            **file_data,
                            "size": target_meta.get("size", 0),
                            "md5Checksum": target_meta.get("md5Checksum", ""),
                            "modifiedTime": target_meta.get("modifiedTime", ""),
                        }
                        # Use target_id for the manifest entry (needed for downloads)
                        file_id = target_id
                    else:
                        # Can't get target metadata, skip
                        stats.skipped += 1
                        continue

            # Check if file is in tracked folders
            if file_data:
                in_tracked = self._is_in_tracked_folders(
                    file_data, tracked_folder_ids
                )
                if not in_tracked:
                    stats.skipped += 1
                    continue

                # Find which root folder this belongs to
                for folder in self.manifest.folders:
                    file_path = self._get_file_path(file_id, folder.folder_id)
                    if file_path:
                        self._update_file_in_folder(
                            folder, file_id, file_data, file_path,
                            file_lookup, stats
                        )
                        break

            if progress_callback:
                progress_callback(stats)

        # Remove deleted files (in reverse order to maintain indices)
        for fi, fli in sorted(files_to_remove, reverse=True):
            folder = self.manifest.folders[fi]
            removed_file = folder.files.pop(fli)
            folder.file_count -= 1
            size = removed_file.get("size", 0) if isinstance(removed_file, dict) else removed_file.size
            folder.total_size -= size

        # Update token
        self.manifest.changes_token = new_token
        stats.api_calls = self.client.api_calls - start_api_calls

        return stats

    def _is_in_tracked_folders(self, file_data: dict, tracked_ids: Set[str]) -> bool:
        """Check if file is within tracked folders by walking parent chain."""
        parents = file_data.get("parents", [])
        if not parents:
            return False

        visited = set()
        to_check = list(parents)

        while to_check:
            parent_id = to_check.pop(0)
            if parent_id in visited:
                continue
            visited.add(parent_id)

            if parent_id in tracked_ids:
                return True

            # Get parent's parents
            parent_data = self.client.get_file_metadata(parent_id, "parents")
            if parent_data:
                to_check.extend(parent_data.get("parents", []))

        return False

    def _get_file_path(self, file_id: str, root_folder_id: str) -> Optional[str]:
        """Get file path relative to a root folder."""
        path_parts = []
        current_id = file_id

        while current_id and current_id != root_folder_id:
            data = self.client.get_file_metadata(current_id, "name,parents")
            if not data:
                return None

            path_parts.insert(0, data.get("name", ""))
            parents = data.get("parents", [])
            if not parents:
                return None

            current_id = parents[0]

        if current_id == root_folder_id:
            return "/".join(path_parts)

        return None

    def _update_file_in_folder(
        self,
        folder: FolderEntry,
        file_id: str,
        file_data: dict,
        file_path: str,
        file_lookup: dict,
        stats: ChangeStats,
    ):
        """Update or add a file entry in a folder."""
        new_entry = {
            "id": file_id,
            "path": file_path,
            "name": file_data.get("name", ""),
            "size": int(file_data.get("size", 0)),
            "md5": file_data.get("md5Checksum", ""),
            "modified": file_data.get("modifiedTime", ""),
        }

        if file_id in file_lookup:
            # Update existing
            fi, fli = file_lookup[file_id]
            old_entry = self.manifest.folders[fi].files[fli]
            old_size = old_entry.get("size", 0) if isinstance(old_entry, dict) else old_entry.size
            self.manifest.folders[fi].files[fli] = new_entry
            self.manifest.folders[fi].total_size += new_entry["size"] - old_size
            stats.modified += 1
        else:
            # Add new
            folder.files.append(new_entry)
            folder.file_count += 1
            folder.total_size += new_entry["size"]
            stats.added += 1
