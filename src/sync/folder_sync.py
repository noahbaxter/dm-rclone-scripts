"""
Folder sync orchestration for DM Chart Sync.

Coordinates downloading, extraction, and purging for folder synchronization.
"""

import time
from pathlib import Path
from typing import Callable, Optional, Union

from ..drive import DriveClient, FolderScanner
from ..core.formatting import dedupe_files_by_newest
from ..ui.primitives import print_long_path_warning, print_section_header, print_separator, wait_with_skip
from ..ui.widgets import display
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
    ) -> tuple[int, int, int, list[str], bool, int]:
        """
        Sync a folder to local disk.

        Args:
            folder: Folder dict from manifest
            base_path: Base download path
            disabled_prefixes: List of path prefixes to exclude (disabled subfolders)

        Returns:
            Tuple of (downloaded, skipped, errors, rate_limited_file_ids, cancelled, bytes_downloaded)
        """
        folder_path = base_path / folder["name"]
        scan_start = time.time()
        disabled_prefixes = disabled_prefixes or []
        filtered_count = 0

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

            # Deduplicate files with same path, keeping only newest version
            manifest_files = dedupe_files_by_newest(manifest_files)

            tasks, skipped, long_paths = plan_downloads(
                manifest_files, folder_path, self.delete_videos,
                sync_state=self.sync_state, folder_name=folder["name"]
            )

            # Warn about long paths on Windows
            if long_paths:
                print_long_path_warning(len(long_paths))
        else:
            # No manifest - need to scan (shouldn't happen with official folders)
            display.scanning_folder()
            scanner = FolderScanner(self.client)

            def progress(folders, files, shortcuts):
                display.scan_progress(folders, files, shortcuts)

            files = scanner.scan_for_sync(folder["folder_id"], folder_path, progress)
            print()

            tasks, skipped, long_paths = plan_downloads(
                [{"id": f["id"], "path": f["path"], "size": f["size"]} for f in files if not f["skip"]],
                folder_path,
                self.delete_videos
            )
            skipped += sum(1 for f in files if f["skip"])

            # Warn about long paths on Windows
            if long_paths:
                print_long_path_warning(len(long_paths))

        # Print folder status
        if not tasks and not skipped:
            display.folder_status_empty(filtered_count)
            return 0, 0, 0, [], False, 0

        if not tasks:
            # All files already synced
            display.folder_status_synced(skipped, filtered_count)
            return 0, skipped, 0, [], False, 0

        # Files to download
        total_size = sum(t.size for t in tasks)
        display.folder_status_downloading(len(tasks), total_size, skipped, filtered_count)

        # Download
        download_start = time.time()
        downloaded, _, errors, rate_limited, cancelled, bytes_downloaded = self.downloader.download_many(
            tasks, sync_state=self.sync_state, drive_name=folder["name"]
        )
        download_time = time.time() - download_start

        if not cancelled:
            display.folder_complete(downloaded, bytes_downloaded, download_time, errors)

        # Clear cache for this folder after download
        clear_folder_cache(folder_path)

        return downloaded, skipped, errors, rate_limited, cancelled, bytes_downloaded

    def download_folders(
        self,
        folders: list,
        indices: list,
        download_path: Path,
        disabled_prefixes_map: dict[str, list[str]] = None
    ) -> bool:
        """Download folders. Returns True if cancelled."""
        download_path.mkdir(parents=True, exist_ok=True)
        disabled_prefixes_map = disabled_prefixes_map or {}

        total_downloaded = 0
        total_skipped = 0
        total_errors = 0
        total_bytes = 0
        total_rate_limited = 0
        was_cancelled = False
        rate_limited_folders: set[str] = set()
        start_time = time.time()

        total_folders = len(indices)
        for i, idx in enumerate(indices, 1):
            folder = folders[idx]
            header = f"[{i}/{total_folders}] {folder['name']}" if total_folders > 1 else folder['name']
            print_section_header(header)

            # Get disabled prefixes for this specific folder
            folder_id = folder.get("folder_id", "")
            disabled_prefixes = disabled_prefixes_map.get(folder_id, [])

            downloaded, skipped, errors, rate_limited_ids, cancelled, bytes_down = self.sync_folder(
                folder, download_path, disabled_prefixes
            )

            total_downloaded += downloaded
            total_skipped += skipped
            total_errors += errors
            total_bytes += bytes_down
            total_rate_limited += len(rate_limited_ids)

            if rate_limited_ids:
                rate_limited_folders.add(folder['name'])

            if cancelled:
                was_cancelled = True
                break

        # Final summary
        elapsed = time.time() - start_time
        print()
        print_separator()

        if was_cancelled:
            display.sync_cancelled(total_downloaded)
        elif total_downloaded > 0:
            display.sync_complete(total_downloaded, total_bytes, elapsed)
        else:
            display.sync_already_synced()

        if total_errors > 0:
            display.sync_errors(total_errors)
        if total_rate_limited > 0:
            display.sync_rate_limited(total_rate_limited)

        if rate_limited_folders:
            display.rate_limit_guidance(rate_limited_folders)

        # Only wait here if cancelled (no purge will follow)
        if was_cancelled:
            wait_with_skip(5, "Continuing in 5s (press any key to skip)")

        return was_cancelled


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

    print_section_header("Purge")

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
                display.purge_drive_disabled(folder_name, len(local_files), folder_size)

                deleted, failed = delete_files(local_files, base_path)
                total_deleted += deleted
                total_failed += failed
                total_size += folder_size
                display.purge_removed(deleted, failed)
            continue

        # Drive is enabled - use plan_purge to get files
        files_to_purge, _ = plan_purge([folder], base_path, user_settings, sync_state)

        if not files_to_purge:
            continue

        folder_size = sum(size for _, size in files_to_purge)
        display.purge_folder(folder_name, len(files_to_purge), folder_size)

        # Show tree structure (abbreviated)
        tree_lines = format_purge_tree(files_to_purge, base_path)
        display.purge_tree_lines(tree_lines)

        # Delete automatically
        deleted, failed = delete_files(files_to_purge, base_path)
        total_deleted += deleted
        total_failed += failed
        total_size += folder_size
        display.purge_removed(deleted, failed)

    # Clean up partial downloads at base level
    partial_files = find_partial_downloads(base_path)
    if partial_files:
        partial_size = sum(size for _, size in partial_files)
        display.purge_partial_downloads(len(partial_files), partial_size)
        deleted, failed = delete_files(partial_files, base_path)
        total_deleted += deleted
        total_failed += failed
        total_size += partial_size
        display.purge_partial_cleaned(deleted, failed)

    print()
    print_separator()
    if total_deleted > 0 or total_failed > 0:
        display.purge_summary(total_deleted, total_size, total_failed)
    else:
        display.purge_nothing()

    # Clean up sync_state entries for files that no longer exist
    if sync_state:
        orphaned = sync_state.cleanup_orphaned_entries()
        if orphaned > 0:
            sync_state.save()

    # Clear cache after purge
    clear_cache()

    # Auto-dismiss after 5 seconds (any key skips)
    wait_with_skip(5, "Continuing in 5s (press any key to skip)")


