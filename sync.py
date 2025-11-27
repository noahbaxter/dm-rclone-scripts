#!/usr/bin/env python3
"""
DM Chart Sync - Download charts from Google Drive without authentication.

This is the user-facing app that downloads chart files using a pre-built
manifest, eliminating the need for users to scan Google Drive.
"""

import os
import sys
from pathlib import Path

import requests

from src import (
    DriveClient,
    Manifest,
    FolderSync,
    purge_all_folders,
    clear_screen,
    print_header,
    show_main_menu,
)
from src.drive_client import DriveClientConfig

# ============================================================================
# Configuration
# ============================================================================

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MANIFEST_URL = "https://github.com/noahbaxter/dm-rclone-scripts/releases/download/manifest/manifest.json"
DOWNLOAD_FOLDER = "Charts"  # Folder next to the app


def get_app_dir() -> Path:
    """Get the directory where the app is located."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_download_path() -> Path:
    """Get the download directory path."""
    return get_app_dir() / DOWNLOAD_FOLDER


def get_manifest_path() -> Path:
    """Get path to local manifest file."""
    return get_app_dir() / "manifest.json"


def fetch_manifest() -> dict:
    """Fetch folder manifest from GitHub, with local fallback."""
    local_path = get_manifest_path()

    # Try remote first
    try:
        response = requests.get(MANIFEST_URL, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception:
        pass

    # Fall back to local
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

    def __init__(self):
        client_config = DriveClientConfig(api_key=API_KEY)
        self.client = DriveClient(client_config)
        self.sync = FolderSync(self.client)
        self.folders = []

    def load_manifest(self):
        """Load manifest folders."""
        print("Fetching folder list...")
        manifest_data = fetch_manifest()
        self.folders = manifest_data.get("folders", [])

    def handle_download(self, indices: list):
        """Handle folder download."""
        cancelled = self.sync.download_folders(self.folders, indices, get_download_path())
        if not cancelled:
            input("\nPress Enter to continue...")

    def handle_purge(self):
        """Purge extra files from all folders."""
        purge_all_folders(self.folders, get_download_path())

    def run(self):
        """Main application loop."""
        clear_screen()
        print_header()
        self.load_manifest()

        while True:
            if not self.folders:
                clear_screen()
                print_header()
                print("No folders available!")
                print()

            choice = show_main_menu(self.folders)

            if choice == "Q":
                print("\nGoodbye!")
                break

            elif choice == "A" and self.folders:
                self.handle_download(list(range(len(self.folders))))

            elif choice == "X":
                self.handle_purge()

            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(self.folders):
                    self.handle_download([idx])
                else:
                    print("Invalid selection")
                    input("Press Enter to continue...")

            else:
                # Handle comma-separated selections
                try:
                    indices = [int(x.strip()) - 1 for x in choice.split(",")]
                    valid_indices = [i for i in indices if 0 <= i < len(self.folders)]
                    if valid_indices:
                        self.handle_download(valid_indices)
                    else:
                        print("Invalid selection")
                        input("Press Enter to continue...")
                except ValueError:
                    print("Invalid selection")
                    input("Press Enter to continue...")


def main():
    """Entry point."""
    app = SyncApp()
    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
