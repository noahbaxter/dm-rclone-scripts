"""
Sync operations for DM Chart Sync.

Handles folder synchronization, file comparison, and purging.
"""

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS
from ..file_ops import find_unexpected_files_with_sizes
from ..utils import format_size, format_duration, print_progress
from ..drive import DriveClient, FolderScanner
from ..ui.keyboard import wait_with_skip
from .downloader import FileDownloader, read_checksum, read_checksum_data, is_archive_file, get_folder_size


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


def _scan_local_files(folder_path: Path) -> dict[str, int]:
    """
    Scan local folder and return dict of {relative_path: size}.

    Uses os.scandir for better performance than individual exists()/stat() calls.
    """
    local_files = {}
    if not folder_path.exists():
        return local_files

    def scan_dir(dir_path: Path, prefix: str = ""):
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    rel_path = f"{prefix}{entry.name}" if prefix else entry.name
                    if entry.is_file(follow_symlinks=False):
                        try:
                            local_files[rel_path] = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        scan_dir(Path(entry.path), f"{rel_path}/")
        except OSError:
            pass

    scan_dir(folder_path)
    return local_files


def _scan_checksums(folder_path: Path) -> dict[str, dict]:
    """
    Scan for all check.txt files and return dict of {parent_path: checksum_data}.

    Much faster than reading check.txt individually for each chart.
    """
    checksums = {}
    if not folder_path.exists():
        return checksums

    checksum_file = "check.txt"

    def scan_dir(dir_path: Path, prefix: str = ""):
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False) and entry.name == checksum_file:
                        # Found a check.txt - read it
                        try:
                            with open(entry.path) as f:
                                data = json.load(f)
                                # Store under the parent directory path (without trailing /)
                                checksums[prefix.rstrip("/")] = data
                        except (json.JSONDecodeError, IOError):
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        rel_path = f"{prefix}{entry.name}/" if prefix else f"{entry.name}/"
                        scan_dir(Path(entry.path), rel_path)
        except OSError:
            pass

    scan_dir(folder_path)
    return checksums


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

        # Get disabled setlists
        disabled_setlists = set()
        if user_settings:
            disabled_setlists = user_settings.get_disabled_subfolders(folder_id)

        # Group files by parent folder to identify charts
        # chart_folders: {parent_path: {files: [...], is_chart: bool, total_size: int, archive_md5: str}}
        chart_folders = defaultdict(lambda: {"files": [], "is_chart": False, "total_size": 0, "archive_md5": ""})

        for f in manifest_files:
            file_path = f.get("path", "")
            file_size = f.get("size", 0)
            file_md5 = f.get("md5", "")

            # Split once, reuse
            slash_idx = file_path.rfind("/")
            if slash_idx == -1:
                continue  # Skip root-level files

            parent = file_path[:slash_idx]
            file_name = file_path[slash_idx + 1:].lower()

            # Skip files in disabled setlists
            if disabled_setlists:
                first_slash = file_path.find("/")
                setlist = file_path[:first_slash] if first_slash != -1 else file_path
                if setlist in disabled_setlists:
                    continue

            chart_folders[parent]["files"].append((file_path, file_size))
            chart_folders[parent]["total_size"] += file_size

            # Check for chart markers (song.ini, notes.mid, etc.)
            if file_name in CHART_MARKERS:
                chart_folders[parent]["is_chart"] = True
            # Check for archive files (.zip, .7z, .rar)
            elif is_archive_file(file_name):
                chart_folders[parent]["is_chart"] = True
                chart_folders[parent]["archive_md5"] = file_md5

        # Batch scan: get all local files and checksums upfront
        local_files = _scan_local_files(folder_path)
        checksums = _scan_checksums(folder_path)

        # Count charts (folders with markers or archives)
        for parent, data in chart_folders.items():
            if not data["is_chart"]:
                continue

            status.total_charts += 1
            status.total_size += data["total_size"]

            # For archive charts, check if check.txt has matching MD5
            if data["archive_md5"]:
                checksum_data = checksums.get(parent, {})
                if checksum_data.get("md5") == data["archive_md5"]:
                    status.synced_charts += 1
                    # Use actual extracted size if available
                    extracted_size = checksum_data.get("size", 0)
                    status.synced_size += extracted_size if extracted_size else data["total_size"]
                continue

            # For folder charts, check if all files exist locally (using pre-scanned data)
            all_synced = True
            for file_path, file_size in data["files"]:
                local_size = local_files.get(file_path)
                if local_size != file_size:
                    all_synced = False
                    break

            if all_synced:
                status.synced_charts += 1
                status.synced_size += data["total_size"]

    return status


class FolderSync:
    """Handles syncing folders from Google Drive to local disk."""

    def __init__(self, client: DriveClient, auth_token: str = None, delete_videos: bool = True):
        self.client = client
        self.downloader = FileDownloader(auth_token=auth_token, delete_videos=delete_videos)

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

    For archive charts, if check.txt exists with matching MD5, the entire
    chart folder is considered valid (extracted contents are expected).

    Returns list of (Path, size) tuples.
    """
    manifest_files = folder.get("files")
    if not manifest_files:
        return []

    folder_path = base_path / folder["name"]
    expected_paths = {folder_path / f["path"] for f in manifest_files}

    # Build a set of chart folders that have valid check.txt (synced archive charts)
    # These folders should be entirely skipped during purge
    valid_archive_folders = set()
    for f in manifest_files:
        file_path = f.get("path", "")
        file_name = file_path.split("/")[-1].lower() if "/" in file_path else file_path.lower()
        file_md5 = f.get("md5", "")

        if is_archive_file(file_name) and file_md5:
            # This is an archive file - check if it's been extracted
            if "/" in file_path:
                parent = "/".join(file_path.split("/")[:-1])
                chart_folder = folder_path / parent
                stored_md5 = read_checksum(chart_folder)
                if stored_md5 == file_md5:
                    # This archive has been extracted - mark folder as valid
                    valid_archive_folders.add(chart_folder)

    # Get all unexpected files
    all_extras = find_unexpected_files_with_sizes(folder_path, expected_paths)

    # Filter out files that are inside valid archive chart folders
    filtered_extras = []
    for file_path, size in all_extras:
        # Check if this file is inside a valid archive folder
        is_in_valid_archive = False
        for valid_folder in valid_archive_folders:
            try:
                file_path.relative_to(valid_folder)
                is_in_valid_archive = True
                break
            except ValueError:
                continue

        if not is_in_valid_archive:
            filtered_extras.append((file_path, size))

    return filtered_extras


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

    # Pre-convert to set for faster lookups
    archive_extensions_set = set(CHART_ARCHIVE_EXTENSIONS)

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

                    slash_idx = file_path.rfind("/")
                    if slash_idx == -1:
                        continue

                    parent = file_path[:slash_idx]
                    file_name = file_path[slash_idx + 1:].lower()

                    chart_folders[parent]["size"] += file_size
                    if file_name in CHART_MARKERS:
                        chart_folders[parent]["has_marker"] = True
                    elif any(file_name.endswith(ext) for ext in archive_extensions_set):
                        chart_folders[parent]["has_marker"] = True

                # Batch scan local files once
                local_files = _scan_local_files(folder_path)

                for parent, data in chart_folders.items():
                    if data["has_marker"]:
                        # Check if chart exists locally using pre-scanned data
                        parent_prefix = f"{parent}/"
                        has_local_marker = any(
                            local_files.get(f"{parent}/{marker}") is not None
                            for marker in CHART_MARKERS
                        )
                        has_local_archive = any(
                            key.startswith(parent_prefix) and
                            any(key.lower().endswith(ext) for ext in archive_extensions_set)
                            for key in local_files
                        ) if not has_local_marker else False

                        if has_local_marker or has_local_archive:
                            total_charts += 1
                            total_size += data["size"]
            continue

        # Drive enabled - count charts in disabled setlists
        disabled_setlists = user_settings.get_disabled_subfolders(folder_id) if user_settings else set()
        if not disabled_setlists or not manifest_files:
            continue

        chart_folders = defaultdict(lambda: {"has_marker": False, "size": 0, "setlist": ""})
        for f in manifest_files:
            file_path = f.get("path", "")
            file_size = f.get("size", 0)

            first_slash = file_path.find("/")
            if first_slash == -1:
                continue

            setlist = file_path[:first_slash]
            if setlist not in disabled_setlists:
                continue

            slash_idx = file_path.rfind("/")
            parent = file_path[:slash_idx]
            file_name = file_path[slash_idx + 1:].lower()

            chart_folders[parent]["size"] += file_size
            chart_folders[parent]["setlist"] = setlist
            if file_name in CHART_MARKERS:
                chart_folders[parent]["has_marker"] = True
            elif any(file_name.endswith(ext) for ext in archive_extensions_set):
                chart_folders[parent]["has_marker"] = True

        # Batch scan local files once
        local_files = _scan_local_files(folder_path)

        for parent, data in chart_folders.items():
            if data["has_marker"]:
                # Check if chart exists locally using pre-scanned data
                parent_prefix = f"{parent}/"
                has_local_marker = any(
                    local_files.get(f"{parent}/{marker}") is not None
                    for marker in CHART_MARKERS
                )
                has_local_archive = any(
                    key.startswith(parent_prefix) and
                    any(key.lower().endswith(ext) for ext in archive_extensions_set)
                    for key in local_files
                ) if not has_local_marker else False

                if has_local_marker or has_local_archive:
                    total_charts += 1
                    total_size += data["size"]

    return total_charts, total_size


def purge_all_folders(folders: list, base_path: Path, user_settings=None):
    """
    Purge files that shouldn't be synced.

    This includes:
    - Files not in the manifest (extra files)
    - Files from disabled drives
    - Files from disabled setlists

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

        # Drive is enabled, check setlist-level
        files_to_purge = []

        # Get disabled setlists
        disabled_setlists = user_settings.get_disabled_subfolders(folder_id) if user_settings else set()

        # Find files in disabled setlists
        for setlist_name in disabled_setlists:
            setlist_path = folder_path / setlist_name
            if setlist_path.exists():
                for f in setlist_path.rglob("*"):
                    if f.is_file():
                        try:
                            files_to_purge.append((f, f.stat().st_size))
                        except Exception:
                            files_to_purge.append((f, 0))

        # Also find extra files not in manifest (for enabled setlists)
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
