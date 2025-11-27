"""
Sync operations for DM Chart Sync.

Handles folder synchronization, file comparison, and purging.
"""

import time
from collections import defaultdict
from pathlib import Path

from .downloader import FileDownloader
from .drive_client import DriveClient
from .scanner import FolderScanner
from .utils import format_size, format_duration, print_progress


class FolderSync:
    """Handles syncing folders from Google Drive to local disk."""

    def __init__(self, client: DriveClient):
        self.client = client
        self.downloader = FileDownloader()

    def sync_folder(self, folder: dict, base_path: Path) -> tuple[int, int, int, bool]:
        """
        Sync a folder to local disk.

        Returns (downloaded, skipped, errors, cancelled).
        """
        folder_path = base_path / folder["name"]
        scan_start = time.time()

        # Use manifest files if available (official folders)
        manifest_files = folder.get("files")

        if manifest_files:
            print(f"  Using manifest ({len(manifest_files)} files)...")
            tasks, skipped = self.downloader.filter_existing(manifest_files, folder_path)
            scan_time = time.time() - scan_start
            print(f"  Comparison completed in {format_duration(scan_time)} (0 API calls)")
        else:
            # Custom folder - need to scan
            print(f"  Scanning folder (custom folder, not in manifest)...")
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

    def download_folders(self, folders: list, indices: list, download_path: Path) -> bool:
        """
        Download selected folders.

        Returns True if cancelled by user, False otherwise.
        """
        print()
        print("=" * 50)
        print("Starting download...")
        print(f"Destination: {download_path}")
        print("=" * 50)
        print()

        download_path.mkdir(parents=True, exist_ok=True)

        total_downloaded = 0
        total_skipped = 0
        total_errors = 0
        was_cancelled = False

        for idx in indices:
            folder = folders[idx]
            print(f"\n[{folder['name']}]")
            print("-" * 40)

            downloaded, skipped, errors, cancelled = self.sync_folder(folder, download_path)

            total_downloaded += downloaded
            total_skipped += skipped
            total_errors += errors

            if cancelled:
                was_cancelled = True
                break

            print(f"  Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")

        if was_cancelled:
            return True

        print()
        print("=" * 50)
        print("Download Complete!")
        print(f"  Total downloaded: {total_downloaded}")
        print(f"  Total skipped (already exists): {total_skipped}")
        print(f"  Total errors: {total_errors}")
        print("=" * 50)

        # Check for extra files (only for official folders with manifests)
        all_extras = []
        for idx in indices:
            folder = folders[idx]
            if folder.get("official") and folder.get("files"):
                extras = find_extra_files(folder, download_path)
                all_extras.extend(extras)

        if all_extras:
            total_extra_size = sum(size for _, size in all_extras)
            print()
            print(f"Found {len(all_extras)} local files not in manifest ({format_size(total_extra_size)})")
            print()

            # Show tree structure
            tree_lines = format_extras_tree(all_extras, download_path)
            for line in tree_lines[:10]:
                print(line)
            if len(tree_lines) > 10:
                print(f"  ... and {len(tree_lines) - 10} more folders")

            print()
            confirm = input("Remove these files? [y/N]: ").strip().lower()
            if confirm == "y":
                deleted = delete_files(all_extras, download_path)
                print(f"Removed {deleted} files ({format_size(total_extra_size)})")

        return False


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
    if not folder_path.exists():
        return []

    # Build set of expected paths
    expected_paths = {folder_path / f["path"] for f in manifest_files}

    # Find all local files
    local_files = [f for f in folder_path.rglob("*") if f.is_file()]

    # Find extras with sizes
    extra_files = []
    for f in local_files:
        if f not in expected_paths:
            try:
                extra_files.append((f, f.stat().st_size))
            except Exception:
                extra_files.append((f, 0))

    return extra_files


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


def purge_extra_files(folder: dict, base_path: Path):
    """
    Find and optionally delete files not in the manifest.

    Args:
        folder: Folder dict with 'files' manifest
        base_path: Base download path
    """
    extras = find_extra_files(folder, base_path)

    if not extras:
        print("  No extra files found.")
        return

    total_size = sum(size for _, size in extras)
    print(f"  Found {len(extras)} files not in manifest ({format_size(total_size)})")
    print()

    # Show tree structure
    tree_lines = format_extras_tree(extras, base_path)
    for line in tree_lines[:10]:
        print(f"  {line}")
    if len(tree_lines) > 10:
        print(f"    ... and {len(tree_lines) - 10} more folders")

    print()
    confirm = input("  Remove these files? [y/N]: ").strip().lower()
    if confirm == "y":
        deleted = delete_files(extras, base_path)
        print(f"  Removed {deleted} files ({format_size(total_size)})")
