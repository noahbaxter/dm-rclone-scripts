"""
Folder sync orchestration for DM Chart Sync.

Coordinates downloading, extraction, and purging for folder synchronization.
"""

import time
from pathlib import Path
from typing import Callable, Optional, Union

from ..drive import DriveClient, FolderScanner
from ..utils import format_size, format_duration, print_progress, print_long_path_warning, dedupe_files_by_newest
from ..ui.keyboard import wait_with_skip
from .cache import clear_cache, clear_folder_cache
from .download_planner import plan_downloads
from .purge_planner import plan_purge, find_partial_downloads
from .purger import delete_files
from .sync_state import SyncState


class FolderSync:
    """Handles syncing folders from Google Drive to local disk."""

    def __init__(
        self,
        client: DriveClient,
        auth_token: Optional[Union[str, Callable[[], Optional[str]]]] = None,
        delete_videos: bool = True,
        sync_state: Optional[SyncState] = None,
    ):
        self.client = client
        self.auth_token = auth_token
        self.delete_videos = delete_videos
        self.sync_state = sync_state
        # Import here to avoid circular dependency
        from .downloader import FileDownloader
        self.downloader = FileDownloader(auth_token=auth_token, delete_videos=delete_videos)

    def sync_folder(
        self,
        folder: dict,
        base_path: Path,
        disabled_prefixes: list[str] = None
    ) -> tuple[int, int, int, int, bool]:
        """
        Sync a folder to local disk.

        Args:
            folder: Folder dict from manifest
            base_path: Base download path
            disabled_prefixes: List of path prefixes to exclude (disabled subfolders)

        Returns (downloaded, skipped, errors, rate_limited, cancelled).
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

            # Deduplicate files with same path, keeping only newest version
            deduped_files = dedupe_files_by_newest(manifest_files)
            dupe_count = len(manifest_files) - len(deduped_files)
            if dupe_count > 0:
                print(f"  Deduplicated {dupe_count} older file versions")
            manifest_files = deduped_files

            print(f"  Using manifest ({len(manifest_files)} files)...")
            tasks, skipped, long_paths = plan_downloads(
                manifest_files, folder_path, self.delete_videos,
                sync_state=self.sync_state, folder_name=folder["name"]
            )
            scan_time = time.time() - scan_start
            print(f"  Comparison completed in {format_duration(scan_time)} (0 API calls)")

            # Warn about long paths on Windows
            if long_paths:
                print_long_path_warning(len(long_paths))
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

            tasks, skipped, long_paths = plan_downloads(
                [{"id": f["id"], "path": f["path"], "size": f["size"]} for f in files if not f["skip"]],
                folder_path,
                self.delete_videos
            )
            skipped += sum(1 for f in files if f["skip"])

            # Warn about long paths on Windows
            if long_paths:
                print_long_path_warning(len(long_paths))

        if not tasks and not skipped:
            print(f"  No files found or error accessing folder")
            return 0, 0, 1, 0, False

        if not tasks:
            print(f"  All {skipped} files already downloaded")
            return 0, skipped, 0, 0, False

        total_size = sum(t.size for t in tasks)
        print(f"  Found {len(tasks)} files to download ({format_size(total_size)}), {skipped} already exist")

        # Download
        download_start = time.time()
        downloaded, _, errors, rate_limited, cancelled = self.downloader.download_many(
            tasks, sync_state=self.sync_state
        )
        download_time = time.time() - download_start

        if not cancelled:
            print(f"  Download completed in {format_duration(download_time)}")
            print(f"  Total time: {format_duration(scan_time + download_time)}")

        # Clear cache for this folder after download
        clear_folder_cache(folder_path)

        return downloaded, skipped, errors, rate_limited, cancelled

    def download_folders(
        self,
        folders: list,
        indices: list,
        download_path: Path,
        disabled_prefixes_map: dict[str, list[str]] = None
    ):
        """
        Download selected folders.

        Automatically retries rate-limited files by re-running the sync
        (which skips already-downloaded files) until everything succeeds.

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
        retry_round = 0
        max_retries = 10  # Safety limit

        while retry_round <= max_retries:
            round_downloaded = 0
            round_rate_limited = 0

            for idx in indices:
                folder = folders[idx]
                if retry_round == 0:
                    print(f"\n[{folder['name']}]")
                else:
                    print(f"\n[{folder['name']}] (retry {retry_round})")
                print("-" * 40)

                # Get disabled prefixes for this specific folder
                folder_id = folder.get("folder_id", "")
                disabled_prefixes = disabled_prefixes_map.get(folder_id, [])

                downloaded, skipped, errors, rate_limited, cancelled = self.sync_folder(
                    folder, download_path, disabled_prefixes
                )

                round_downloaded += downloaded
                round_rate_limited += rate_limited
                total_downloaded += downloaded
                total_skipped += skipped
                total_errors += errors

                if cancelled:
                    was_cancelled = True
                    break

                if rate_limited > 0:
                    print(f"  Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}, Rate-limited: {rate_limited}")
                else:
                    print(f"  Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")

            if was_cancelled:
                break

            # If we had rate-limited files, wait and retry
            if round_rate_limited > 0:
                retry_round += 1
                wait_time = min(60, 15 + retry_round * 10)  # 25s, 35s, 45s, ... up to 60s
                print(f"\n  {round_rate_limited} files were rate-limited. Waiting {wait_time}s before retry...")
                print("  (Press Ctrl+C to cancel)")
                try:
                    time.sleep(wait_time)
                except KeyboardInterrupt:
                    was_cancelled = True
                    print("\n  Cancelled.")
                    break
            else:
                # No rate limiting, we're done
                break

        if was_cancelled:
            return

        print()
        print("=" * 50)
        print("Download Complete!")
        print(f"  Total downloaded: {total_downloaded}")
        print(f"  Total skipped (already exists): {total_skipped}")
        print(f"  Total errors: {total_errors}")
        if retry_round > 0:
            print(f"  Retry rounds needed: {retry_round}")
        print("=" * 50)

        # Auto-dismiss after 2 seconds (any key skips)
        wait_with_skip(2)


def purge_all_folders(
    folders: list,
    base_path: Path,
    user_settings=None,
    sync_state: Optional[SyncState] = None,
):
    """
    Purge files that shouldn't be synced.

    This includes:
    - Files not in the manifest (extra files)
    - Files from disabled drives
    - Files from disabled setlists
    - Partial downloads (interrupted archive downloads with _download_ prefix)
    - Video files (when delete_videos is enabled)

    Args:
        folders: List of folder dicts from manifest
        base_path: Base download path
        user_settings: UserSettings instance for checking enabled states
        sync_state: SyncState instance for checking tracked files (optional)
    """
    from ..ui.purge_display import format_purge_tree

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

        # Drive is enabled - use plan_purge to get files
        files_to_purge, _ = plan_purge([folder], base_path, user_settings, sync_state)

        if not files_to_purge:
            continue

        folder_size = sum(size for _, size in files_to_purge)
        print(f"\n[{folder_name}]")
        print(f"  Found {len(files_to_purge)} files to purge ({format_size(folder_size)})")

        # Show tree structure (abbreviated)
        tree_lines = format_purge_tree(files_to_purge, base_path)
        for line in tree_lines[:5]:
            print(f"  {line}")
        if len(tree_lines) > 5:
            print(f"    ... and {len(tree_lines) - 5} more folders")

        # Delete automatically
        deleted = delete_files(files_to_purge, base_path)
        total_deleted += deleted
        total_size += folder_size
        print(f"  Removed {deleted} files")

    # Clean up partial downloads at base level
    partial_files = find_partial_downloads(base_path)
    if partial_files:
        partial_size = sum(size for _, size in partial_files)
        print(f"\n[Partial Downloads]")
        print(f"  Found {len(partial_files)} incomplete download(s) ({format_size(partial_size)})")
        deleted = delete_files(partial_files, base_path)
        total_deleted += deleted
        total_size += partial_size
        print(f"  Cleaned up {deleted} file(s)")

    print()
    if total_deleted > 0:
        print(f"Total: Removed {total_deleted} files ({format_size(total_size)})")
    else:
        print("No files to purge.")

    # Clear cache after purge
    clear_cache()

    # Auto-dismiss after 2 seconds (any key skips)
    wait_with_skip(2)


