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
    UserConfig,
    FolderSync,
    purge_extra_files,
    clear_screen,
    print_header,
    show_main_menu,
    show_purge_menu,
    add_custom_folder,
    remove_custom_folder,
    change_download_path,
)
from src.drive_client import DriveClientConfig

# ============================================================================
# Configuration
# ============================================================================

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MANIFEST_URL = "https://github.com/noahbaxter/dm-rclone-scripts/releases/download/manifest/manifest.json"


def get_manifest_path() -> Path:
    """Get path to local manifest file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "manifest.json"
    return Path(__file__).parent / "manifest.json"


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

    print("Warning: Could not load folder manifest.")
    print("Use [C] to add folders manually.\n")
    return {"folders": []}


# ============================================================================
# Main Application
# ============================================================================


class SyncApp:
    """Main application controller."""

    def __init__(self):
        self.config = UserConfig.load()
        client_config = DriveClientConfig(api_key=API_KEY)
        self.client = DriveClient(client_config)
        self.sync = FolderSync(self.client)
        self.manifest_data = {}

    def load_manifest(self):
        """Load manifest and mark official folders."""
        print("Fetching folder list...")
        self.manifest_data = fetch_manifest()
        for folder in self.manifest_data.get("folders", []):
            folder["official"] = True

    def get_all_folders(self) -> list:
        """Get combined list of official and custom folders."""
        return self.manifest_data.get("folders", []) + [
            {
                "name": f.name,
                "folder_id": f.folder_id,
                "description": f.description,
                "official": False,
            }
            for f in self.config.custom_folders
        ]

    def handle_download(self, folders: list, indices: list):
        """Handle folder download."""
        cancelled = self.sync.download_folders(folders, indices, self.config.resolve_download_path())
        if not cancelled:
            input("\nPress Enter to continue...")

    def handle_purge(self, folders: list):
        """Handle purge menu."""
        choice = show_purge_menu(folders)

        if choice == "C":
            return
        elif choice == "A":
            base_path = self.config.resolve_download_path()
            for folder in folders:
                if folder.get("official"):
                    print(f"\n[{folder['name']}]")
                    purge_extra_files(folder, base_path)
            input("\nPress Enter to continue...")
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(folders) and folders[idx].get("official"):
                print(f"\n[{folders[idx]['name']}]")
                purge_extra_files(folders[idx], self.config.resolve_download_path())
                input("\nPress Enter to continue...")

    def run(self):
        """Main application loop."""
        clear_screen()
        print_header()
        self.load_manifest()

        while True:
            clear_screen()
            print_header()

            all_folders = self.get_all_folders()

            if not all_folders:
                print("No folders available!")
                print("Use [C] to add a custom folder.")
                print()

            choice = show_main_menu(all_folders, self.config)

            if choice == "Q":
                print("\nGoodbye!")
                break

            elif choice == "A" and all_folders:
                self.handle_download(all_folders, list(range(len(all_folders))))

            elif choice == "X":
                self.handle_purge(all_folders)

            elif choice == "C":
                add_custom_folder(self.config, self.client)

            elif choice == "R":
                remove_custom_folder(self.config)

            elif choice == "P":
                change_download_path(self.config)

            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(all_folders):
                    self.handle_download(all_folders, [idx])
                else:
                    print("Invalid selection")
                    input("Press Enter to continue...")

            else:
                # Handle comma-separated selections
                try:
                    indices = [int(x.strip()) - 1 for x in choice.split(",")]
                    valid_indices = [i for i in indices if 0 <= i < len(all_folders)]
                    if valid_indices:
                        self.handle_download(all_folders, valid_indices)
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
