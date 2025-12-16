"""
Folder sync orchestration for DM Chart Sync.

Coordinates downloading, extraction, and purging for folder synchronization.
"""

import time
from pathlib import Path
from typing import Callable, Optional, Union

from ..drive import DriveClient, FolderScanner
from ..core.formatting import format_size, format_duration, dedupe_files_by_newest
from ..ui.primitives import print_progress, print_long_path_warning, wait_with_skip
from .cache import clear_cache, clear_folder_cache
from .download_planner import plan_downloads
from .purge_planner import plan_purge, find_partial_downloads
from .purger import delete_files
from .state import SyncState


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
        disabled_prefixes: list[str] = None,
        skip_file_ids: set[str] = None
    ) -> tuple[int, int, int, list[str], bool]:
        """
        Sync a folder to local disk.

        Args:
            folder: Folder dict from manifest
            base_path: Base download path
            disabled_prefixes: List of path prefixes to exclude (disabled subfolders)
            skip_file_ids: Set of file IDs to skip (e.g., permanently rate-limited)

        Returns:
            Tuple of (downloaded, skipped, errors, rate_limited_file_ids, cancelled)
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
            return 0, 0, 1, [], False

        # Filter out permanently skipped files (e.g., exceeded retry limit)
        if skip_file_ids:
            original_count = len(tasks)
            tasks = [t for t in tasks if t.file_id not in skip_file_ids]
            skipped += original_count - len(tasks)

        if not tasks:
            print(f"  All {skipped} files already downloaded")
            return 0, skipped, 0, [], False

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
        Files that fail 3+ times are skipped and reported at the end.

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
        max_retries = 10  # Safety limit for total retry rounds
        max_per_file_retries = 3  # Skip files after this many failures

        # Track per-file retry counts: {file_id: retry_count}
        file_retry_counts: dict[str, int] = {}
        permanently_skipped: set[str] = set()

        while retry_round <= max_retries:
            round_downloaded = 0
            round_rate_limited_ids: list[str] = []

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

                downloaded, skipped, errors, rate_limited_ids, cancelled = self.sync_folder(
                    folder, download_path, disabled_prefixes, skip_file_ids=permanently_skipped
                )

                round_downloaded += downloaded
                round_rate_limited_ids.extend(rate_limited_ids)
                total_downloaded += downloaded
                total_skipped += skipped
                total_errors += errors

                if cancelled:
                    was_cancelled = True
                    break

                if len(rate_limited_ids) > 0:
                    print(f"  Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}, Rate-limited: {len(rate_limited_ids)}")
                else:
                    print(f"  Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")

            if was_cancelled:
                break

            # Update per-file retry counts and check for files to permanently skip
            new_permanent_skips = []
            for file_id in round_rate_limited_ids:
                file_retry_counts[file_id] = file_retry_counts.get(file_id, 0) + 1
                if file_retry_counts[file_id] >= max_per_file_retries:
                    permanently_skipped.add(file_id)
                    new_permanent_skips.append(file_id)

            if new_permanent_skips:
                print(f"\n  Skipping {len(new_permanent_skips)} file(s) after {max_per_file_retries} failed attempts")

            # Count files still needing retry (not permanently skipped)
            still_rate_limited = [fid for fid in round_rate_limited_ids if fid not in permanently_skipped]

            # If we had rate-limited files that aren't permanently skipped, wait and retry
            if still_rate_limited:
                retry_round += 1
                wait_time = min(60, 15 + retry_round * 10)  # 25s, 35s, 45s, ... up to 60s
                print(f"\n  {len(still_rate_limited)} files were rate-limited. Waiting {wait_time}s before retry...")
                print("  (Press Ctrl+C to cancel)")
                try:
                    time.sleep(wait_time)
                except KeyboardInterrupt:
                    was_cancelled = True
                    print("\n  Cancelled.")
                    break
            else:
                # No more files to retry, we're done
                break

        if was_cancelled:
            return

        print()
        print("=" * 50)
        print("Download Complete!")
        print(f"  Total downloaded: {total_downloaded}")
        print(f"  Total skipped (already exists): {total_skipped}")
        print(f"  Total errors: {total_errors}")
        if permanently_skipped:
            print(f"  Skipped due to rate limits: {len(permanently_skipped)}")
        if retry_round > 0:
            print(f"  Retry rounds needed: {retry_round}")
        print("=" * 50)

        # Report permanently skipped files
        if permanently_skipped:
            print()
            print(f"  {len(permanently_skipped)} file(s) were skipped after repeated rate limiting.")
            print("  These files will be retried on the next sync.")

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
    from ..ui.components import format_purge_tree

    print()
    print("=" * 50)
    print("Purging disabled/extra files...")
    print("=" * 50)

    total_deleted = 0
    total_failed = 0
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

                deleted, failed = delete_files(local_files, base_path)
                total_deleted += deleted
                total_failed += failed
                total_size += folder_size
                print(f"  Removed {deleted} files" + (f" ({failed} failed)" if failed else ""))
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
        deleted, failed = delete_files(files_to_purge, base_path)
        total_deleted += deleted
        total_failed += failed
        total_size += folder_size
        print(f"  Removed {deleted} files" + (f" ({failed} failed)" if failed else ""))

    # Clean up partial downloads at base level
    partial_files = find_partial_downloads(base_path)
    if partial_files:
        partial_size = sum(size for _, size in partial_files)
        print(f"\n[Partial Downloads]")
        print(f"  Found {len(partial_files)} incomplete download(s) ({format_size(partial_size)})")
        deleted, failed = delete_files(partial_files, base_path)
        total_deleted += deleted
        total_failed += failed
        total_size += partial_size
        print(f"  Cleaned up {deleted} file(s)" + (f" ({failed} failed)" if failed else ""))

    print()
    if total_deleted > 0 or total_failed > 0:
        msg = f"Total: Removed {total_deleted} files ({format_size(total_size)})"
        if total_failed > 0:
            msg += f"\n  {total_failed} file(s) could not be deleted (permission errors)"
        print(msg)
    else:
        print("No files to purge.")

    # Clear cache after purge
    clear_cache()

    # Auto-dismiss after 2 seconds (any key skips)
    wait_with_skip(2)


