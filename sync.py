#!/usr/bin/env python3
"""
DM Chart Sync - Download charts from Google Drive without authentication.

This is the user-facing app that downloads chart files using a pre-built
manifest, eliminating the need for users to scan Google Drive.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from src.drive import DriveClient, AuthManager
from src.manifest import Manifest, fetch_manifest
from src.sync import FolderSync, purge_all_folders
from src.sync.state import SyncState
from src.config import UserSettings, DrivesConfig, CustomFolders, extract_subfolders_from_manifest
from src.core.formatting import format_size
from src.core.paths import (
    get_data_dir,
    get_settings_path,
    get_token_path,
    get_local_manifest_path,
    get_download_path,
    get_drives_config_path,
    migrate_legacy_files,
    cleanup_tmp_dir,
)
from src.ui import (
    print_header,
    show_main_menu,
    show_subfolder_settings,
    show_confirmation,
    show_oauth_prompt,
    show_add_custom_folder,
    Colors,
    compute_main_menu_cache,
)
from src.sync import FolderStatsCache, count_purgeable_detailed, clear_scan_cache
from src.ui.primitives import clear_screen, wait_with_skip
from src.ui.primitives.terminal import set_terminal_size
from src.core.logging import TeeOutput
from src.drive.client import DriveClientConfig

# ============================================================================
# Configuration
# ============================================================================

API_KEY = os.environ.get("GOOGLE_API_KEY", "")


# ============================================================================
# Main Application
# ============================================================================


class SyncApp:
    """Main application controller."""

    def __init__(self, use_local_manifest: bool = False):
        client_config = DriveClientConfig(api_key=API_KEY)
        self.client = DriveClient(client_config)

        # Load user settings first (needed for sync options)
        self.user_settings = UserSettings.load(get_settings_path())
        self.drives_config = DrivesConfig.load(get_drives_config_path())

        # Load custom folders
        self.custom_folders = CustomFolders.load(get_local_manifest_path())

        # Unified auth manager (handles user + admin fallback, token refresh)
        self.auth = AuthManager(token_path=get_token_path())

        # Clean up any leftover temp files from interrupted operations
        cleanup_tmp_dir()

        # Load sync state (tracks all synced files)
        self.sync_state = SyncState(get_download_path())
        self.sync_state.load()

        # Clean up legacy check.txt files (replaced by sync_state.json)
        deleted = self.sync_state.cleanup_check_txt_files()
        if deleted > 0:
            print(f"Cleaned up {deleted} legacy check.txt file(s)")

        self.sync = FolderSync(
            self.client,
            auth_token=self.auth.get_token_getter(),
            delete_videos=self.user_settings.delete_videos,
            sync_state=self.sync_state,
        )
        self.folders = []
        self.use_local_manifest = use_local_manifest
        self.folder_stats_cache = FolderStatsCache()

    def load_manifest(self, quiet: bool = False):
        """Load manifest folders (includes custom folders)."""
        if not quiet:
            if self.use_local_manifest:
                print("Loading local manifest...")
            else:
                print("Fetching folder list...")
        manifest_data = fetch_manifest(use_local=self.use_local_manifest)

        # Filter out hidden drives
        hidden_ids = {d.folder_id for d in self.drives_config.drives if d.hidden}
        self.folders = [
            f for f in manifest_data.get("folders", [])
            if f.get("folder_id") not in hidden_ids
        ]

        # Add custom folders to the folders list
        for custom in self.custom_folders.folders:
            # Create folder dict in same format as manifest folders
            files = self.custom_folders.get_files(custom.folder_id)
            folder_dict = {
                "name": custom.name,
                "folder_id": custom.folder_id,
                "description": "Custom folder",
                "file_count": len(files),
                "total_size": sum(f.get("size", 0) for f in files),
                "files": files,
                "complete": True,
                "is_custom": True,  # Mark as custom for special handling
            }
            self.folders.append(folder_dict)

    def handle_sync(self):
        """Sync all enabled folders: download missing files, then purge extras.

        This ensures local state matches the manifest exactly.
        """
        indices = list(range(len(self.folders)))

        # Filter out disabled drives
        enabled_indices = [
            i for i in indices
            if self.user_settings.is_drive_enabled(self.folders[i].get("folder_id", ""))
        ]

        if not enabled_indices:
            print("\nNo drives enabled. Enable at least one drive to sync.")
            return

        # Scan custom folders that need scanning (no files yet)
        self._scan_custom_folders_if_needed(enabled_indices)

        # Get disabled subfolders for filtering
        disabled_map = self._get_disabled_subfolders_for_folders(enabled_indices)

        # Step 1: Download missing files
        self.sync.download_folders(self.folders, enabled_indices, get_download_path(), disabled_map)
        clear_scan_cache()  # Invalidate filesystem cache after download
        self.folder_stats_cache.invalidate_all()  # Invalidate all folder stats

        # Step 2: Purge extra files (no confirmation - sync means make it match)
        stats = count_purgeable_detailed(
            self.folders, get_download_path(), self.user_settings, self.sync_state
        )

        if stats.total_files > 0:
            print()
            print("=" * 50)
            print("Cleaning up extra files...")
            print("=" * 50)

            # Build summary of what's being purged
            parts = []
            if stats.chart_count > 0:
                parts.append(f"{stats.chart_count} chart files ({format_size(stats.chart_size)})")
            if stats.extra_file_count > 0:
                parts.append(f"{stats.extra_file_count} extra files ({format_size(stats.extra_file_size)})")
            if stats.partial_count > 0:
                parts.append(f"{stats.partial_count} partial downloads ({format_size(stats.partial_size)})")

            print(f"Removing: {', '.join(parts)}")

            purge_all_folders(self.folders, get_download_path(), self.user_settings, self.sync_state)
            clear_scan_cache()  # Invalidate filesystem cache after purge
            self.folder_stats_cache.invalidate_all()  # Invalidate all folder stats

            print("Cleanup complete.")
        else:
            print("\nSync complete - no extra files to clean up.")

    def handle_configure_drive(self, folder_id: str):
        """Configure setlists for a specific drive, or show options for custom folders."""
        folder = self._get_folder_by_id(folder_id)
        if not folder:
            return

        # Show subfolder settings (works for both regular and custom folders)
        result = show_subfolder_settings(folder, self.user_settings, get_download_path(), self.sync_state)

        # Invalidate this folder's stats (setlists may have changed)
        self.folder_stats_cache.invalidate(folder_id)

        # Handle custom folder actions
        if result == "scan":
            self._scan_single_custom_folder(folder)
        elif result == "remove":
            self._remove_custom_folder(folder.get("folder_id"), folder.get("name"))

    def _show_custom_folder_options(self, folder: dict):
        """Show options menu for a custom folder."""
        from src.ui import Menu, MenuItem, MenuDivider
        from src.config import extract_subfolders_from_manifest

        folder_id = folder.get("folder_id")
        folder_name = folder.get("name")
        has_files = bool(folder.get("files"))

        # Check if folder has setlists (subfolders)
        setlists = extract_subfolders_from_manifest(folder) if has_files else []

        menu = Menu(title=folder_name)

        # Setlist settings (if folder has subfolders)
        if setlists:
            enabled_count = sum(
                1 for s in setlists
                if self.user_settings.is_subfolder_enabled(folder_id, s)
            )
            menu.add_item(MenuItem(
                "Configure setlists",
                hotkey="C",
                value="setlists",
                description=f"{enabled_count}/{len(setlists)} enabled"
            ))
            menu.add_item(MenuDivider())

        # Scan option
        if has_files:
            menu.add_item(MenuItem("Re-scan folder", hotkey="S", value="scan", description="Refresh file list from Google Drive"))
        else:
            menu.add_item(MenuItem("Scan folder", hotkey="S", value="scan", description="Get file list from Google Drive"))

        menu.add_item(MenuDivider())
        menu.add_item(MenuItem("Remove folder", hotkey="R", value="remove", description="Remove from custom folders"))
        menu.add_item(MenuDivider())
        menu.add_item(MenuItem("Back", value="back"))

        result = menu.run()
        if not result or result.value == "back":
            return

        if result.value == "setlists":
            show_subfolder_settings(folder, self.user_settings, get_download_path(), self.sync_state)
        elif result.value == "scan":
            self._scan_single_custom_folder(folder)
        elif result.value == "remove":
            self._remove_custom_folder(folder_id, folder_name)

    def _scan_single_custom_folder(self, folder: dict):
        """Scan a single custom folder."""
        from src.drive import FolderScanner

        if not self.auth.is_signed_in:
            print("\n  Please sign in to Google first to scan custom folders.")
            wait_with_skip(3)
            return

        folder_id = folder.get("folder_id")
        folder_name = folder.get("name")

        print()
        print("=" * 50)
        print(f"Scanning: {folder_name}")
        print("=" * 50)

        auth_token = self.auth.get_token()
        client_config = DriveClientConfig(api_key=API_KEY)
        auth_client = DriveClient(client_config, auth_token=auth_token)
        scanner = FolderScanner(auth_client)

        def progress_cb(folders_scanned, files_found, shortcuts_found, files_list=None):
            print(f"\r  Scanning... {folders_scanned} folders, {files_found} files found", end="", flush=True)

        result = scanner.scan(folder_id, progress_callback=progress_cb)
        print()

        if result.cancelled:
            print("  Scan cancelled.")
            wait_with_skip(2)
            return

        # Update folder dict with scan results
        folder["files"] = [
            {
                "id": f["id"],
                "path": f["path"],
                "name": f["name"],
                "size": f.get("size", 0),
                "md5": f.get("md5", ""),
                "modified": f.get("modified", ""),
            }
            for f in result.files
        ]
        folder["file_count"] = len(result.files)
        folder["total_size"] = sum(f.get("size", 0) for f in result.files)

        # Save to custom folders storage
        self.custom_folders.set_files(folder_id, folder["files"])
        self.custom_folders.save()

        print(f"  Done! Found {len(result.files)} files ({format_size(folder['total_size'])})")
        print()
        wait_with_skip(2)

    def _remove_custom_folder(self, folder_id: str, folder_name: str):
        """Remove a custom folder after confirmation."""
        if not show_confirmation(
            "Remove custom folder?",
            f"This will remove '{folder_name}' from your custom folders.\nDownloaded files will NOT be deleted."
        ):
            return

        self.custom_folders.remove_folder(folder_id)
        self.custom_folders.save()

        # Remove from folders list
        self.folders = [f for f in self.folders if f.get("folder_id") != folder_id]

        print(f"\n  Removed: {folder_name}")
        wait_with_skip(2)

    def handle_toggle_drive(self, folder_id: str):
        """Toggle a drive on/off at the top level (preserves setlist settings)."""
        self.user_settings.toggle_drive(folder_id)
        self.user_settings.save()
        # Only invalidate this folder's stats
        self.folder_stats_cache.invalidate(folder_id)

    def handle_toggle_group(self, group_name: str):
        """Toggle a group expanded/collapsed."""
        self.user_settings.toggle_group_expanded(group_name)
        self.user_settings.save()

    def handle_signin(self):
        """Handle Google sign-in."""
        print("\n  Opening browser for Google sign-in...")
        print("  (If browser doesn't open, check your terminal)")
        print()

        if self.auth.sign_in():
            print("  Signed in successfully!")
            # Recreate sync with new token
            self._refresh_sync_token()
        else:
            print("  Sign-in cancelled or failed.")

        wait_with_skip(2)

    def handle_signout(self):
        """Handle Google sign-out."""
        self.auth.sign_out()
        # Recreate sync without user token (falls back to admin or anonymous)
        self._refresh_sync_token()
        print("\n  Signed out of Google.")
        wait_with_skip(2)

    def handle_add_custom_folder(self) -> bool:
        """
        Handle adding a custom Google Drive folder.

        Returns True if a folder was added successfully.
        """
        # Require sign-in for custom folders (need OAuth to access user's Drive)
        if not self.auth.is_signed_in:
            print("\n  Please sign in to Google first to add custom folders.")
            print("  Custom folders require access to your Google Drive.")
            wait_with_skip(3)
            return False

        # Create a client with user's OAuth token for validation
        auth_token = self.auth.get_token()
        client_config = DriveClientConfig(api_key=API_KEY)
        auth_client = DriveClient(client_config, auth_token=auth_token)

        # Show add folder screen
        folder_id, folder_name = show_add_custom_folder(auth_client, self.auth)

        if not folder_id:
            return False

        # Check if already exists
        if self.custom_folders.has_folder(folder_id):
            print(f"\n  Folder already added: {folder_name}")
            wait_with_skip(2)
            return False

        # Add to custom folders
        is_first_custom = len(self.custom_folders.folders) == 0
        self.custom_folders.add_folder(folder_id, folder_name)
        self.custom_folders.save()

        # Enable the drive by default
        self.user_settings.set_drive_enabled(folder_id, True)
        # Expand Custom group when first custom folder is added
        if is_first_custom:
            self.user_settings.group_expanded["Custom"] = True
        self.user_settings.save()

        print(f"\n  Added: {folder_name}")

        # Offer to scan now
        if show_confirmation("Scan folder now?", "Scanning finds all files and setlists in the folder."):
            # Create folder dict for scanning
            folder_dict = {
                "name": folder_name,
                "folder_id": folder_id,
                "files": [],
                "is_custom": True,
            }
            self._scan_single_custom_folder(folder_dict)
            # Reload manifest to pick up scanned files
            self.load_manifest()
        else:
            print("  You can scan later from the folder options.")
            wait_with_skip(2)

        return True

    def _refresh_sync_token(self):
        """Recreate FolderSync with current auth token getter."""
        self.sync = FolderSync(
            self.client,
            auth_token=self.auth.get_token_getter(),
            delete_videos=self.user_settings.delete_videos,
            sync_state=self.sync_state,
        )

    def _get_folder_by_id(self, folder_id: str) -> dict | None:
        """Get folder dict by folder_id."""
        for folder in self.folders:
            if folder.get("folder_id", "") == folder_id:
                return folder
        return None

    def _scan_custom_folders_if_needed(self, enabled_indices: list):
        """
        Scan any custom folders that haven't been scanned yet.

        Custom folders need to be scanned using the user's OAuth token
        before they can be downloaded.
        """
        from src.drive import FolderScanner

        # Find custom folders that need scanning
        folders_to_scan = []
        for idx in enabled_indices:
            folder = self.folders[idx]
            if folder.get("is_custom") and not folder.get("files"):
                folders_to_scan.append((idx, folder))

        if not folders_to_scan:
            return

        # Need user OAuth for scanning
        if not self.auth.is_signed_in:
            print("\n  Cannot scan custom folders: not signed in to Google.")
            print("  Sign in first to download from custom folders.")
            wait_with_skip(3)
            return

        # Show scanning header
        print()
        print("=" * 50)
        print("Scanning custom folders...")
        print("=" * 50)

        # Create scanner with user's OAuth
        auth_token = self.auth.get_token()
        client_config = DriveClientConfig(api_key=API_KEY)
        auth_client = DriveClient(client_config, auth_token=auth_token)
        scanner = FolderScanner(auth_client)

        for idx, folder in folders_to_scan:
            folder_id = folder.get("folder_id")
            folder_name = folder.get("name")

            print(f"\n[{folder_name}]")
            print("-" * 40)

            def progress_cb(folders_scanned, files_found, shortcuts_found, files_list=None):
                print(f"\r  Scanning... {folders_scanned} folders, {files_found} files found", end="", flush=True)

            result = scanner.scan(folder_id, progress_callback=progress_cb)
            print()  # New line after progress

            if result.cancelled:
                print("  Scan cancelled.")
                continue

            # Update folder dict with scan results
            folder["files"] = [
                {
                    "id": f["id"],
                    "path": f["path"],
                    "name": f["name"],
                    "size": f.get("size", 0),
                    "md5": f.get("md5", ""),
                    "modified": f.get("modified", ""),
                }
                for f in result.files
            ]
            folder["file_count"] = len(result.files)
            folder["total_size"] = sum(f.get("size", 0) for f in result.files)

            # Save to custom folders storage
            self.custom_folders.set_files(folder_id, folder["files"])
            self.custom_folders.save()

            print(f"  Done! Found {len(result.files)} files ({format_size(folder['total_size'])})")

        print()
        print("=" * 50)
        print("Scan complete. Starting download...")
        print("=" * 50)

    def _get_combined_drives_config(self) -> DrivesConfig:
        """Get drives config with custom folders added as a group."""
        from src.config import DriveConfig

        # Create a copy of drives list with custom folders appended
        combined = DrivesConfig(self.drives_config.path)
        combined.drives = list(self.drives_config.drives)

        # Add custom folders as a group
        for custom in self.custom_folders.folders:
            combined.drives.append(DriveConfig(
                name=custom.name,
                folder_id=custom.folder_id,
                description="Custom folder",
                group="Custom",
            ))

        return combined

    def _get_disabled_subfolders_for_folders(self, indices: list) -> dict[str, list[str]]:
        """
        Get disabled subfolder names for the selected folders.

        Returns dict mapping folder_id to list of disabled subfolder names.
        """
        result = {}
        for idx in indices:
            folder = self.folders[idx]
            folder_id = folder.get("folder_id", "")
            disabled = self.user_settings.get_disabled_subfolders(folder_id)
            if disabled:
                result[folder_id] = list(disabled)

        return result

    def run(self):
        """Main application loop."""
        clear_screen()
        print_header()

        # First-run OAuth prompt (only shown once)
        if not self.user_settings.oauth_prompted and self.auth.is_available:
            self.user_settings.oauth_prompted = True
            self.user_settings.save()

            if show_oauth_prompt():
                self.handle_signin()
                clear_screen()
                print_header()

        self.load_manifest()

        selected_index = 0  # Track selected position for maintaining after actions
        menu_cache = None  # Cache for expensive menu calculations

        while True:
            if not self.folders:
                clear_screen()
                print_header()
                print("No folders available!")
                print()

            # Compute cache if needed (first run or after state-changing actions)
            # Use combined drives config that includes custom folders
            combined_drives = self._get_combined_drives_config()

            if menu_cache is None:
                menu_cache = compute_main_menu_cache(
                    self.folders, self.user_settings,
                    get_download_path(), combined_drives,
                    self.sync_state, self.folder_stats_cache
                )

            action, value, menu_pos = show_main_menu(
                self.folders, self.user_settings, selected_index,
                get_download_path(), combined_drives, cache=menu_cache,
                auth=self.auth, sync_state=self.sync_state
            )
            selected_index = menu_pos  # Always preserve menu position

            if action == "quit":
                print("\nGoodbye!")
                break

            elif action == "sync":
                if self.folders:
                    self.handle_sync()
                menu_cache = None  # Invalidate cache after sync

            elif action == "configure":
                # Enter on a drive - go directly to configure that drive
                self.handle_configure_drive(value)
                menu_cache = None  # Invalidate cache after configure (setlists may change)

            elif action == "toggle":
                # Space on a drive - toggle drive on/off
                self.handle_toggle_drive(value)
                menu_cache = None  # Invalidate cache after toggle

            elif action == "toggle_group":
                # Enter/Space on a group - expand/collapse (NO cache invalidation!)
                self.handle_toggle_group(value)
                # Keep using the same cache - just showing/hiding items

            elif action == "cycle_delta_mode":
                # Tab - cycle between size/files display mode
                self.user_settings.cycle_delta_mode()
                self.user_settings.save()
                self.folder_stats_cache.invalidate_all()  # Clear cached display strings
                menu_cache = None  # Invalidate cache to refresh display

            elif action == "signin":
                self.handle_signin()
                # No cache invalidation needed - just auth state changed

            elif action == "signout":
                self.handle_signout()
                # No cache invalidation needed - just auth state changed

            elif action == "add_custom":
                if self.handle_add_custom_folder():
                    # Reload folders to include the new custom folder
                    self.load_manifest(quiet=True)
                    menu_cache = None  # Invalidate cache - new folder added


def main():
    """Entry point."""
    # Set terminal to consistent size for proper rendering
    set_terminal_size(90, 40)

    parser = argparse.ArgumentParser(
        description="DM Chart Sync - Download charts from Google Drive"
    )
    parser.add_argument(
        "--local-manifest",
        action="store_true",
        help="Use local manifest.json instead of fetching from GitHub"
    )
    args = parser.parse_args()

    # Always log to .dm-sync/logs/YYYY-MM-DD.log
    logs_dir = get_data_dir() / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    tee = TeeOutput(log_path)
    sys.stdout = tee

    # Migrate legacy files from old locations to .dm-sync/
    # Must run BEFORE creating SyncApp so paths resolve correctly
    migrated = migrate_legacy_files()
    if migrated:
        print(f"Migrated settings to .dm-sync/: {', '.join(migrated)}")

    app = SyncApp(use_local_manifest=args.local_manifest)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
