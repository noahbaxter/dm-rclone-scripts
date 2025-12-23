"""
Folder sync orchestration for DM Chart Sync.

Coordinates downloading, extraction, and purging for folder synchronization.
"""

import time
from pathlib import Path
from typing import Callable, Optional, Union

from ..drive import DriveClient, FolderScanner
from ..core.formatting import format_size, format_duration, format_speed, dedupe_files_by_newest
from ..ui.primitives import print_progress, print_long_path_warning, print_section_header, print_separator, wait_with_skip
from ..ui.primitives.colors import Colors
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
        c = Colors
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
            print(f"  {c.DIM}Scanning folder...{c.RESET}")
            scanner = FolderScanner(self.client)

            def progress(folders, files, shortcuts):
                shortcut_info = f", {shortcuts} shortcuts" if shortcuts else ""
                print_progress(f"Scanning... {folders} folders, {files} files{shortcut_info}")

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

        # Build consolidated status parts
        status_parts = []

        if not tasks and not skipped:
            status_parts.append("no files")
            if filtered_count > 0:
                status_parts.append(f"{c.DIM}{filtered_count} filtered{c.RESET}")
            print(f"  {', '.join(status_parts)}")
            return 0, 0, 0, [], False, 0

        if not tasks:
            # All files already synced
            status_parts.append(f"{skipped} files")
            if filtered_count > 0:
                status_parts.append(f"{c.DIM}{filtered_count} filtered{c.RESET}")
            print(f"  {', '.join(status_parts)} • {c.GREEN}✓ synced{c.RESET}")
            return 0, skipped, 0, [], False, 0

        # Files to download
        total_size = sum(t.size for t in tasks)
        status_parts.append(f"{len(tasks)} files ({format_size(total_size)})")
        if skipped > 0:
            status_parts.append(f"{skipped} synced")
        if filtered_count > 0:
            status_parts.append(f"{c.DIM}{filtered_count} filtered{c.RESET}")
        print(f"  {', '.join(status_parts)}")

        # Download
        download_start = time.time()
        downloaded, _, errors, rate_limited, cancelled, bytes_downloaded = self.downloader.download_many(
            tasks, sync_state=self.sync_state, drive_name=folder["name"]
        )
        download_time = time.time() - download_start

        if not cancelled:
            # Final summary line
            avg_speed = bytes_downloaded / download_time if download_time > 0 else 0
            summary = f"  {c.GREEN}✓{c.RESET} {downloaded} files"
            if bytes_downloaded > 0:
                summary += f" ({format_size(bytes_downloaded)})"
            summary += f" in {format_duration(download_time)}"
            if avg_speed > 0:
                summary += f" • {format_speed(avg_speed)}"
            if errors > 0:
                summary += f" • {c.RED}{errors} errors{c.RESET}"
            print(summary)

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
        c = Colors
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

        for idx in indices:
            folder = folders[idx]
            print_section_header(folder['name'])

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
            summary = f"{c.DIM}Cancelled{c.RESET}"
            if total_downloaded > 0:
                summary += f" - {total_downloaded} files downloaded"
            print(summary)
        elif total_downloaded > 0:
            avg_speed = total_bytes / elapsed if elapsed > 0 else 0
            summary = f"{c.GREEN}✓{c.RESET} {total_downloaded} files"
            if total_bytes > 0:
                summary += f" ({format_size(total_bytes)})"
            summary += f" in {format_duration(elapsed)}"
            if avg_speed > 0:
                summary += f" • {format_speed(avg_speed)} avg"
            print(summary)
        else:
            print(f"{c.GREEN}✓{c.RESET} All files synced")

        if total_errors > 0:
            print(f"  {c.RED}{total_errors} errors{c.RESET}")
        if total_rate_limited > 0:
            print(f"  {c.DIM}{total_rate_limited} rate-limited{c.RESET}")

        # Give guidance for rate-limited folders
        if rate_limited_folders:
            print()
            folder_list = ", ".join(sorted(rate_limited_folders))
            print(f"  {c.DIM}[{folder_list}] hit Google's download limit.{c.RESET}")
            print(f"  {c.DIM}Run sync again later, or try tomorrow (resets every 24h).{c.RESET}")

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

    c = Colors

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
                print(f"\n{c.DIM}[{folder_name}]{c.RESET} (drive disabled)")
                print(f"  Found {c.RED}{len(local_files)}{c.RESET} files ({format_size(folder_size)})")

                deleted, failed = delete_files(local_files, base_path)
                total_deleted += deleted
                total_failed += failed
                total_size += folder_size
                print(f"  {c.RED}Removed {deleted} files{c.RESET}" + (f" ({failed} failed)" if failed else ""))
            continue

        # Drive is enabled - use plan_purge to get files
        files_to_purge, _ = plan_purge([folder], base_path, user_settings, sync_state)

        if not files_to_purge:
            continue

        folder_size = sum(size for _, size in files_to_purge)
        print(f"\n{c.DIM}[{folder_name}]{c.RESET}")
        print(f"  Found {c.RED}{len(files_to_purge)}{c.RESET} files to purge ({format_size(folder_size)})")

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
        print(f"  {c.RED}Removed {deleted} files{c.RESET}" + (f" ({failed} failed)" if failed else ""))

    # Clean up partial downloads at base level
    partial_files = find_partial_downloads(base_path)
    if partial_files:
        partial_size = sum(size for _, size in partial_files)
        print(f"\n{c.DIM}[Partial Downloads]{c.RESET}")
        print(f"  Found {c.RED}{len(partial_files)}{c.RESET} incomplete download(s) ({format_size(partial_size)})")
        deleted, failed = delete_files(partial_files, base_path)
        total_deleted += deleted
        total_failed += failed
        total_size += partial_size
        print(f"  {c.RED}Cleaned up {deleted} file(s){c.RESET}" + (f" ({failed} failed)" if failed else ""))

    print()
    print_separator()
    if total_deleted > 0 or total_failed > 0:
        print(f"{c.RED}✗{c.RESET} Removed {total_deleted} files ({format_size(total_size)})")
        if total_failed > 0:
            print(f"  {c.DIM}{total_failed} file(s) could not be deleted{c.RESET}")
    else:
        print(f"{c.GREEN}✓{c.RESET} No files to purge")

    # Clean up sync_state entries for files that no longer exist
    if sync_state:
        orphaned = sync_state.cleanup_orphaned_entries()
        if orphaned > 0:
            sync_state.save()

    # Clear cache after purge
    clear_cache()

    # Auto-dismiss after 5 seconds (any key skips)
    wait_with_skip(5, "Continuing in 5s (press any key to skip)")


