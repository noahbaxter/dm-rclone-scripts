"""
Sync operations for DM Chart Sync.

Handles folder synchronization, file comparison, and purging.
"""

import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..constants import CHART_MARKERS
from ..file_ops import find_unexpected_files_with_sizes
from ..utils import format_size, format_duration, print_progress
from ..drive import DriveClient, FolderScanner
from ..ui.keyboard import wait_with_skip
from .downloader import FileDownloader


@dataclass
class SyncStatus:
    """Status of local charts vs manifest."""
    total_charts: int = 0
    synced_charts: int = 0
    total_size: int = 0
    synced_size: int = 0

    @property
    def missing_charts(self) -> int:
        return self.total_charts - self.synced_charts

    @property
    def missing_size(self) -> int:
        return self.total_size - self.synced_size

    @property
    def is_synced(self) -> bool:
        return self.synced_charts == self.total_charts


def get_sync_status(folders: list, base_path: Path, user_settings=None) -> SyncStatus:
    """
    Calculate sync status for enabled folders (counts charts, not files).

    Args:
        folders: List of folder dicts from manifest
        base_path: Base download path
        user_settings: UserSettings for checking enabled states

    Returns:
        SyncStatus with chart totals and synced counts
    """
    status = SyncStatus()

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name

        # Skip disabled drives
        if user_settings and not user_settings.is_drive_enabled(folder_id):
            continue

        manifest_files = folder.get("files", [])
        if not manifest_files:
            continue

        # Get disabled charters
        disabled_charters = set()
        if user_settings:
            disabled_charters = user_settings.get_disabled_subfolders(folder_id)

        # Group files by parent folder to identify charts
        # chart_folders: {parent_path: {files: [...], has_marker: bool, total_size: int}}
        chart_folders = defaultdict(lambda: {"files": [], "has_marker": False, "total_size": 0})

        for f in manifest_files:
            file_path = f.get("path", "")
            file_size = f.get("size", 0)
            file_name = file_path.split("/")[-1].lower() if "/" in file_path else file_path.lower()

            # Skip files in disabled charters
            if disabled_charters:
                parts = file_path.split("/")
                if parts and parts[0] in disabled_charters:
                    continue

            # Get parent folder path
            if "/" in file_path:
                parent = "/".join(file_path.split("/")[:-1])
            else:
                continue  # Skip root-level files

            chart_folders[parent]["files"].append((file_path, file_size))
            chart_folders[parent]["total_size"] += file_size

            if file_name in CHART_MARKERS:
                chart_folders[parent]["has_marker"] = True

        # Count charts (folders with markers)
        for parent, data in chart_folders.items():
            if not data["has_marker"]:
                continue

            status.total_charts += 1
            status.total_size += data["total_size"]

            # Check if all files in this chart exist locally
            all_synced = True
            synced_size = 0
            for file_path, file_size in data["files"]:
                local_path = folder_path / file_path
                if local_path.exists():
                    try:
                        if local_path.stat().st_size == file_size:
                            synced_size += file_size
                        else:
                            all_synced = False
                    except Exception:
                        all_synced = False
                else:
                    all_synced = False

            if all_synced:
                status.synced_charts += 1
                status.synced_size += data["total_size"]

    return status


class FolderSync:
    """Handles syncing folders from Google Drive to local disk."""

    def __init__(self, client: DriveClient):
        self.client = client
        self.downloader = FileDownloader()

    def sync_folder(
        self,
        folder: dict,
        base_path: Path,
        disabled_prefixes: list[str] = None
    ) -> tuple[int, int, int, bool]:
        """
        Sync a folder to local disk.

        Args:
            folder: Folder dict from manifest
            base_path: Base download path
            disabled_prefixes: List of path prefixes to exclude (disabled subfolders)

        Returns (downloaded, skipped, errors, cancelled).
        """
        folder_path = base_path / folder["name"]
        scan_start = time.time()
        disabled_prefixes = disabled_prefixes or []

        # Use manifest files if available (official folders)
        manifest_files = folder.get("files")

        if manifest_files:
            # Filter out files in disabled subfolders
            if disabled_prefixes:
                original_count = len(manifest_files)
                manifest_files = [
                    f for f in manifest_files
                    if not any(f.get("path", "").startswith(prefix + "/") or f.get("path", "") == prefix
                               for prefix in disabled_prefixes)
                ]
                filtered_count = original_count - len(manifest_files)
                if filtered_count > 0:
                    print(f"  Filtered out {filtered_count} files from disabled subfolders")

            print(f"  Using manifest ({len(manifest_files)} files)...")
            tasks, skipped = self.downloader.filter_existing(manifest_files, folder_path)
            scan_time = time.time() - scan_start
            print(f"  Comparison completed in {format_duration(scan_time)} (0 API calls)")
        else:
            # No manifest - need to scan (shouldn't happen with official folders)
            print(f"  Scanning folder...")
            scanner = FolderScanner(self.client)

            def progress(folders, files, shortcuts):
                shortcut_info = f", {shortcuts} shortcuts" if shortcuts else ""
                print_progress(f"Scanning... {folders} folders, {files} files{shortcut_info}")

            files = scanner.scan_for_sync(folder["folder_id"], folder_path, progress)
            print()
            scan_time = time.time() - scan_start
            print(f"  Scan completed in {format_duration(scan_time)}")

            tasks, skipped = self.downloader.filter_existing(
                [{"id": f["id"], "path": f["path"], "size": f["size"]} for f in files if not f["skip"]],
                folder_path
            )
            skipped += sum(1 for f in files if f["skip"])

        if not tasks and not skipped:
            print(f"  No files found or error accessing folder")
            return 0, 0, 1, False

        if not tasks:
            print(f"  All {skipped} files already downloaded")
            return 0, skipped, 0, False

        total_size = sum(t.size for t in tasks)
        print(f"  Found {len(tasks)} files to download ({format_size(total_size)}), {skipped} already exist")

        # Download
        download_start = time.time()
        downloaded, _, errors, cancelled = self.downloader.download_many(tasks)
        download_time = time.time() - download_start

        if not cancelled:
            print(f"  Download completed in {format_duration(download_time)}")
            print(f"  Total time: {format_duration(scan_time + download_time)}")

        return downloaded, skipped, errors, cancelled

    def download_folders(
        self,
        folders: list,
        indices: list,
        download_path: Path,
        disabled_prefixes_map: dict[str, list[str]] = None
    ):
        """
        Download selected folders.

        Args:
            folders: List of folder dicts from manifest
            indices: List of folder indices to download
            download_path: Base download path
            disabled_prefixes_map: Dict mapping folder_id to list of disabled path prefixes
        """
        print()
        print("=" * 50)
        print("Starting download...")
        print(f"Destination: {download_path}")
        print("=" * 50)
        print()

        download_path.mkdir(parents=True, exist_ok=True)
        disabled_prefixes_map = disabled_prefixes_map or {}

        total_downloaded = 0
        total_skipped = 0
        total_errors = 0
        was_cancelled = False

        for idx in indices:
            folder = folders[idx]
            print(f"\n[{folder['name']}]")
            print("-" * 40)

            # Get disabled prefixes for this specific folder
            folder_id = folder.get("folder_id", "")
            disabled_prefixes = disabled_prefixes_map.get(folder_id, [])

            downloaded, skipped, errors, cancelled = self.sync_folder(
                folder, download_path, disabled_prefixes
            )

            total_downloaded += downloaded
            total_skipped += skipped
            total_errors += errors

            if cancelled:
                was_cancelled = True
                break

            print(f"  Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")

        if was_cancelled:
            return

        print()
        print("=" * 50)
        print("Download Complete!")
        print(f"  Total downloaded: {total_downloaded}")
        print(f"  Total skipped (already exists): {total_skipped}")
        print(f"  Total errors: {total_errors}")
        print("=" * 50)

        # Auto-dismiss after 2 seconds (any key skips)
        wait_with_skip(2)


def format_extras_tree(files: list, base_path: Path) -> list[str]:
    """
    Format extra files as a tree showing file counts per folder.

    Returns list of formatted strings to print.
    """
    # Group files by parent directory
    by_folder = defaultdict(lambda: {"count": 0, "size": 0})
    for f, size in files:
        rel_path = f.relative_to(base_path)
        parent = str(rel_path.parent)
        by_folder[parent]["count"] += 1
        by_folder[parent]["size"] += size

    # Sort by path for nice tree display
    sorted_folders = sorted(by_folder.items())

    lines = []
    for folder_path, stats in sorted_folders:
        file_word = "file" if stats["count"] == 1 else "files"
        lines.append(f"  {folder_path}/ ({stats['count']} {file_word}, {format_size(stats['size'])})")

    return lines


def find_extra_files(folder: dict, base_path: Path) -> list:
    """
    Find local files not in the manifest.

    Returns list of (Path, size) tuples.
    """
    manifest_files = folder.get("files")
    if not manifest_files:
        return []

    folder_path = base_path / folder["name"]
    expected_paths = {folder_path / f["path"] for f in manifest_files}

    return find_unexpected_files_with_sizes(folder_path, expected_paths)


def delete_files(files: list, base_path: Path) -> int:
    """
    Delete files and clean up empty directories.

    Args:
        files: List of (Path, size) tuples
        base_path: Base path to clean empty dirs under

    Returns number of files deleted.
    """
    deleted = 0
    for f, _ in files:
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass

    # Clean up empty directories
    try:
        for d in sorted(base_path.rglob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    except Exception:
        pass

    return deleted


def count_purgeable_charts(folders: list, base_path: Path, user_settings=None) -> tuple[int, int]:
    """
    Count charts that would be purged based on manifest chart definitions.

    Uses the same logic as get_sync_status - a chart is defined by the manifest's
    folder structure, not by scanning local disk for markers.

    Returns:
        Tuple of (chart_count, total_size)
    """
    total_charts = 0
    total_size = 0

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name

        if not folder_path.exists():
            continue

        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        manifest_files = folder.get("files", [])

        if not drive_enabled:
            # Count synced charts in disabled drive using manifest
            if manifest_files:
                chart_folders = defaultdict(lambda: {"has_marker": False, "size": 0})
                for f in manifest_files:
                    file_path = f.get("path", "")
                    file_size = f.get("size", 0)
                    file_name = file_path.split("/")[-1].lower() if "/" in file_path else file_path.lower()
                    if "/" in file_path:
                        parent = "/".join(file_path.split("/")[:-1])
                        chart_folders[parent]["size"] += file_size
                        if file_name in CHART_MARKERS:
                            chart_folders[parent]["has_marker"] = True

                for parent, data in chart_folders.items():
                    if data["has_marker"]:
                        # Check if chart exists locally (at least the marker file)
                        local_parent = folder_path / parent
                        has_local_marker = any(
                            (local_parent / marker).exists() for marker in CHART_MARKERS
                        )
                        if has_local_marker:
                            total_charts += 1
                            total_size += data["size"]
            continue

        # Drive enabled - count charts in disabled charters
        disabled_charters = user_settings.get_disabled_subfolders(folder_id) if user_settings else set()
        if not disabled_charters or not manifest_files:
            continue

        chart_folders = defaultdict(lambda: {"has_marker": False, "size": 0, "charter": ""})
        for f in manifest_files:
            file_path = f.get("path", "")
            file_size = f.get("size", 0)
            file_name = file_path.split("/")[-1].lower() if "/" in file_path else file_path.lower()
            parts = file_path.split("/")

            if len(parts) < 2:
                continue

            charter = parts[0]
            if charter not in disabled_charters:
                continue

            parent = "/".join(parts[:-1])
            chart_folders[parent]["size"] += file_size
            chart_folders[parent]["charter"] = charter
            if file_name in CHART_MARKERS:
                chart_folders[parent]["has_marker"] = True

        for parent, data in chart_folders.items():
            if data["has_marker"]:
                local_parent = folder_path / parent
                has_local_marker = any(
                    (local_parent / marker).exists() for marker in CHART_MARKERS
                )
                if has_local_marker:
                    total_charts += 1
                    total_size += data["size"]

    return total_charts, total_size


def purge_all_folders(folders: list, base_path: Path, user_settings=None):
    """
    Purge files that shouldn't be synced.

    This includes:
    - Files not in the manifest (extra files)
    - Files from disabled drives
    - Files from disabled charters

    Args:
        folders: List of folder dicts from manifest
        base_path: Base download path
        user_settings: UserSettings instance for checking enabled states
    """
    print()
    print("=" * 50)
    print("Purging disabled/extra files...")
    print("=" * 50)

    total_deleted = 0
    total_size = 0

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name

        if not folder_path.exists():
            continue

        # Check if entire drive is disabled
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        if not drive_enabled:
            # Purge entire drive folder
            local_files = [(f, f.stat().st_size if f.exists() else 0)
                          for f in folder_path.rglob("*") if f.is_file()]
            if local_files:
                folder_size = sum(size for _, size in local_files)
                print(f"\n[{folder_name}] (drive disabled)")
                print(f"  Found {len(local_files)} files ({format_size(folder_size)})")

                deleted = delete_files(local_files, base_path)
                total_deleted += deleted
                total_size += folder_size
                print(f"  Removed {deleted} files")
            continue

        # Drive is enabled, check charter-level
        files_to_purge = []

        # Get disabled charters
        disabled_charters = user_settings.get_disabled_subfolders(folder_id) if user_settings else set()

        # Find files in disabled charters
        for charter_name in disabled_charters:
            charter_path = folder_path / charter_name
            if charter_path.exists():
                for f in charter_path.rglob("*"):
                    if f.is_file():
                        try:
                            files_to_purge.append((f, f.stat().st_size))
                        except Exception:
                            files_to_purge.append((f, 0))

        # Also find extra files not in manifest (for enabled charters)
        extras = find_extra_files(folder, base_path)
        files_to_purge.extend(extras)

        # Deduplicate
        seen = set()
        unique_files = []
        for f, size in files_to_purge:
            if f not in seen:
                seen.add(f)
                unique_files.append((f, size))

        if not unique_files:
            continue

        folder_size = sum(size for _, size in unique_files)
        print(f"\n[{folder_name}]")
        print(f"  Found {len(unique_files)} files to purge ({format_size(folder_size)})")

        # Show tree structure (abbreviated)
        tree_lines = format_extras_tree(unique_files, base_path)
        for line in tree_lines[:5]:
            print(f"  {line}")
        if len(tree_lines) > 5:
            print(f"    ... and {len(tree_lines) - 5} more folders")

        # Delete automatically
        deleted = delete_files(unique_files, base_path)
        total_deleted += deleted
        total_size += folder_size
        print(f"  Removed {deleted} files")

    print()
    if total_deleted > 0:
        print(f"Total: Removed {total_deleted} files ({format_size(total_size)})")
    else:
        print("No files to purge.")

    # Auto-dismiss after 2 seconds (any key skips)
    wait_with_skip(2)
