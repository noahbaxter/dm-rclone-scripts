"""
Folder scanner for DM Chart Sync.

Recursively scans Google Drive folders to build file lists.
"""

from pathlib import Path
from typing import Callable, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .client import DriveClient
from ..core.files import file_exists_with_size


@dataclass
class ScanResult:
    """Result of a folder scan."""
    files: list
    folder_count: int
    shortcut_count: int
    api_calls: int
    cancelled: bool = False  # True if scan was interrupted by Ctrl+C


class FolderScanner:
    """
    Recursively scans Google Drive folders.

    Features:
    - Parallel folder scanning for speed
    - Handles shortcuts (links to other drives)
    - Progress callbacks for UI updates
    """

    FOLDER_MIME = "application/vnd.google-apps.folder"
    SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

    def __init__(self, client: DriveClient, max_workers: int = 8):
        """
        Initialize the scanner.

        Args:
            client: DriveClient instance for API calls
            max_workers: Number of parallel scanning threads
        """
        self.client = client
        self.max_workers = max_workers

    def scan(
        self,
        folder_id: str,
        base_path: str = "",
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> ScanResult:
        """
        Recursively scan a folder and return all files.

        Args:
            folder_id: Google Drive folder ID to scan
            base_path: Base path prefix for file paths
            progress_callback: Optional callback(folders_scanned, files_found, shortcuts_found)

        Returns:
            ScanResult with files list and stats (cancelled=True if interrupted)
        """
        all_files = []
        folders_to_scan = [(folder_id, base_path)]
        folder_count = 0
        shortcut_count = 0
        start_api_calls = self.client.api_calls
        cancelled = False

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                while folders_to_scan:
                    # Submit batch of folder scans
                    futures = {
                        executor.submit(self.client.list_folder, fid): (fid, fpath)
                        for fid, fpath in folders_to_scan
                    }
                    folders_to_scan = []

                    for future in as_completed(futures):
                        folder_id_done, folder_path = futures[future]
                        try:
                            items = future.result()
                            folder_count += 1

                            for item in items:
                                item_name = item["name"]
                                item_path = f"{folder_path}/{item_name}" if folder_path else item_name
                                mime_type = item["mimeType"]

                                # Handle regular folders
                                if mime_type == self.FOLDER_MIME:
                                    folders_to_scan.append((item["id"], item_path))

                                # Handle shortcuts (links to other drives)
                                elif mime_type == self.SHORTCUT_MIME:
                                    shortcut_details = item.get("shortcutDetails", {})
                                    target_id = shortcut_details.get("targetId")
                                    target_mime = shortcut_details.get("targetMimeType", "")

                                    if target_id and target_mime == self.FOLDER_MIME:
                                        # Shortcut to folder - follow it
                                        shortcut_count += 1
                                        folders_to_scan.append((target_id, item_path))
                                    elif target_id:
                                        # Shortcut to file - need to fetch target's metadata
                                        # (shortcuts don't have size/md5, only the target file does)
                                        target_meta = self.client.get_file_metadata(
                                            target_id,
                                            fields="id,name,size,md5Checksum,modifiedTime"
                                        )
                                        if target_meta:
                                            all_files.append({
                                                "id": target_id,
                                                "path": item_path,
                                                "name": item_name,
                                                "size": int(target_meta.get("size", 0)),
                                                "md5": target_meta.get("md5Checksum", ""),
                                                "modified": target_meta.get("modifiedTime", ""),
                                            })

                                # Handle regular files
                                else:
                                    all_files.append({
                                        "id": item["id"],
                                        "path": item_path,
                                        "name": item_name,
                                        "size": int(item.get("size", 0)),
                                        "md5": item.get("md5Checksum", ""),
                                        "modified": item.get("modifiedTime", ""),
                                    })

                            # Progress callback (includes files list for chart counting)
                            if progress_callback:
                                progress_callback(folder_count, len(all_files), shortcut_count, all_files)

                        except Exception as e:
                            # Log error but continue scanning
                            print(f"\n  Error scanning folder: {e}")

        except KeyboardInterrupt:
            cancelled = True
            print("\n  Scan interrupted by user (Ctrl+C)")

        return ScanResult(
            files=all_files,
            folder_count=folder_count,
            shortcut_count=shortcut_count,
            api_calls=self.client.api_calls - start_api_calls,
            cancelled=cancelled,
        )

    def scan_for_sync(
        self,
        folder_id: str,
        local_base: Path,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> List[dict]:
        """
        Scan folder and compare against local files.

        Args:
            folder_id: Google Drive folder ID
            local_base: Local base path for comparison
            progress_callback: Optional progress callback

        Returns:
            List of file dicts with 'skip' flag indicating if file exists locally
        """
        result = self.scan(folder_id, "", progress_callback)

        # Add skip flag based on local file existence
        for f in result.files:
            local_path = local_base / f["path"]
            f["skip"] = file_exists_with_size(local_path, f.get("size", 0))

        return result.files
