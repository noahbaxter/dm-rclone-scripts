#!/usr/bin/env python3
"""
DM Chart Sync - Download charts from Google Drive without authentication.

This is the user-facing app that downloads chart files using a pre-built
manifest, eliminating the need for users to scan Google Drive.
"""

import argparse
import os
import sys
from pathlib import Path

import requests

from src import (
    DriveClient,
    Manifest,
    FolderSync,
    OAuthManager,
    purge_all_folders,
    clear_screen,
    print_header,
    show_main_menu,
    show_subfolder_settings,
    show_confirmation,
    UserSettings,
    DrivesConfig,
    extract_subfolders_from_manifest,
    compute_main_menu_cache,
    format_size,
)
from src.sync.operations import count_purgeable_charts
from src.drive.client import DriveClientConfig

# ============================================================================
# Configuration
# ============================================================================

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MANIFEST_URL = "https://github.com/noahbaxter/dm-rclone-scripts/releases/download/manifest/manifest.json"
DOWNLOAD_FOLDER = "Sync Charts"  # Folder next to the app


def get_app_dir() -> Path:
    """Get the directory where the app is located (for user-writable files)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_bundle_dir() -> Path:
    """Get the directory where bundled resources are located (PyInstaller)."""
    if getattr(sys, "frozen", False):
        # PyInstaller extracts bundled files to _MEIPASS temp directory
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_download_path() -> Path:
    """Get the download directory path."""
    return get_app_dir() / DOWNLOAD_FOLDER


def get_manifest_path() -> Path:
    """Get path to local manifest file."""
    return get_app_dir() / "manifest.json"


def get_user_settings_path() -> Path:
    """Get path to user settings file."""
    return get_app_dir() / "user_settings.json"


def get_drives_config_path() -> Path:
    """Get path to drives config file (bundled with app)."""
    return get_bundle_dir() / "drives.json"


def fetch_manifest(use_local: bool = False) -> dict:
    """
    Fetch folder manifest.

    Args:
        use_local: If True, only read from local manifest.json (skip remote)

    Returns:
        Manifest data as dict
    """
    local_path = get_manifest_path()

    if not use_local:
        # Try remote first
        try:
            response = requests.get(MANIFEST_URL, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception:
            pass

    # Use local manifest
    if local_path.exists():
        manifest = Manifest.load(local_path)
        return manifest.to_dict()

    print("Warning: Could not load folder manifest.\n")
    return {"folders": []}


# ============================================================================
# Main Application
# ============================================================================


class SyncApp:
    """Main application controller."""

    def __init__(self, use_local_manifest: bool = False):
        client_config = DriveClientConfig(api_key=API_KEY)
        self.client = DriveClient(client_config)

        # Load user settings first (needed for sync options)
        self.user_settings = UserSettings.load(get_user_settings_path())
        self.drives_config = DrivesConfig.load(get_drives_config_path())

        # Get OAuth token for authenticated downloads if available
        auth_token = None
        auth = OAuthManager()
        if auth.is_available and auth.is_configured:
            auth_token = auth.get_token()

        self.sync = FolderSync(
            self.client,
            auth_token=auth_token,
            delete_videos=self.user_settings.delete_videos
        )
        self.folders = []
        self.use_local_manifest = use_local_manifest

    def load_manifest(self):
        """Load manifest folders."""
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

    def handle_download(self, indices: list):
        """Handle folder download."""
        # Filter out disabled drives
        enabled_indices = [
            i for i in indices
            if self.user_settings.is_drive_enabled(self.folders[i].get("folder_id", ""))
        ]

        if not enabled_indices:
            print("\nNo drives enabled. Enable at least one drive to download.")
            return

        # Get disabled subfolders for filtering
        disabled_map = self._get_disabled_subfolders_for_folders(enabled_indices)
        self.sync.download_folders(self.folders, enabled_indices, get_download_path(), disabled_map)

    def handle_purge(self) -> bool:
        """Purge disabled/extra files from all folders.

        Returns:
            True if purge was performed, False if cancelled or nothing to purge.
        """
        # Check what would be purged
        purge_count, purge_size = count_purgeable_charts(
            self.folders, get_download_path(), self.user_settings
        )

        if purge_count == 0:
            return False

        # Show confirmation
        message = f"This will delete {purge_count} charts ({format_size(purge_size)})"
        if not show_confirmation("Are you sure you want to purge?", message):
            return False

        purge_all_folders(self.folders, get_download_path(), self.user_settings)
        return True

    def handle_configure_drive(self, folder_id: str):
        """Configure setlists for a specific drive."""
        folder = self._get_folder_by_id(folder_id)
        if folder:
            show_subfolder_settings(folder, self.user_settings, get_download_path())

    def handle_toggle_drive(self, folder_id: str):
        """Toggle a drive on/off at the top level (preserves setlist settings)."""
        self.user_settings.toggle_drive(folder_id)
        self.user_settings.save()

    def handle_toggle_group(self, group_name: str):
        """Toggle a group expanded/collapsed."""
        self.user_settings.toggle_group_expanded(group_name)
        self.user_settings.save()

    def _get_folder_by_id(self, folder_id: str) -> dict | None:
        """Get folder dict by folder_id."""
        for folder in self.folders:
            if folder.get("folder_id", "") == folder_id:
                return folder
        return None

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
            if menu_cache is None:
                menu_cache = compute_main_menu_cache(
                    self.folders, self.user_settings,
                    get_download_path(), self.drives_config
                )

            action, value, menu_pos = show_main_menu(
                self.folders, self.user_settings, selected_index,
                get_download_path(), self.drives_config, cache=menu_cache
            )
            selected_index = menu_pos  # Always preserve menu position

            if action == "quit":
                print("\nGoodbye!")
                break

            elif action == "download":
                if self.folders:
                    self.handle_download(list(range(len(self.folders))))
                menu_cache = None  # Invalidate cache after download

            elif action == "purge":
                self.handle_purge()
                menu_cache = None  # Invalidate cache after purge

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


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="DM Chart Sync - Download charts from Google Drive"
    )
    parser.add_argument(
        "--local-manifest",
        action="store_true",
        help="Use local manifest.json instead of fetching from GitHub"
    )
    args = parser.parse_args()

    app = SyncApp(use_local_manifest=args.local_manifest)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
