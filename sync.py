#!/usr/bin/env python3
"""
DM Chart Sync - Download charts from Google Drive without authentication.

This is the user-facing app that downloads chart files using a pre-built
manifest, eliminating the need for users to scan Google Drive.
"""

import os
import re
import sys
import time
from pathlib import Path

import requests

from src import (
    DriveClient,
    Manifest,
    UserConfig,
    FileDownloader,
    FolderScanner,
    format_size,
    format_duration,
    print_progress,
)
from src.drive_client import DriveClientConfig

# ============================================================================
# Configuration
# ============================================================================

API_KEY = "AIzaSyDhCOPZRechLiL5PqFqiybvKOrmtaGR6lE"
MANIFEST_URL = "https://raw.githubusercontent.com/noahbaxter/dm-rclone-scripts/main/manifest.json"

# ============================================================================
# Utilities
# ============================================================================


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def get_manifest_path() -> Path:
    """Get path to local manifest file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "manifest.json"
    return Path(__file__).parent / "manifest.json"


def extract_folder_id(url_or_id: str) -> str | None:
    """Extract folder ID from Google Drive URL or return as-is if already an ID."""
    match = re.search(r"folders/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
    if re.match(r"^[a-zA-Z0-9_-]+$", url_or_id):
        return url_or_id
    return None


# ============================================================================
# Manifest Loading
# ============================================================================


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
# Sync Operations
# ============================================================================


def format_extras_tree(files: list, base_path: Path) -> list[str]:
    """
    Format extra files as a tree showing file counts per folder.

    Returns list of formatted strings to print.
    """
    from collections import defaultdict

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


def sync_folder(folder: dict, base_path: Path, client: DriveClient) -> tuple:
    """
    Sync a folder to local disk.

    Returns (downloaded, skipped, errors).
    """
    folder_path = base_path / folder["name"]
    downloader = FileDownloader()

    scan_start = time.time()

    # Use manifest files if available (official folders)
    manifest_files = folder.get("files")

    if manifest_files:
        print(f"  Using manifest ({len(manifest_files)} files)...")
        tasks, skipped = downloader.filter_existing(manifest_files, folder_path)
        scan_time = time.time() - scan_start
        print(f"  Comparison completed in {format_duration(scan_time)} (0 API calls)")
    else:
        # Custom folder - need to scan
        print(f"  Scanning folder (custom folder, not in manifest)...")
        scanner = FolderScanner(client)

        def progress(folders, files, shortcuts):
            shortcut_info = f", {shortcuts} shortcuts" if shortcuts else ""
            print_progress(f"Scanning... {folders} folders, {files} files{shortcut_info}")

        files = scanner.scan_for_sync(folder["folder_id"], folder_path, progress)
        print()
        scan_time = time.time() - scan_start
        print(f"  Scan completed in {format_duration(scan_time)}")

        tasks, skipped = downloader.filter_existing(
            [{"id": f["id"], "path": f["path"], "size": f["size"]} for f in files if not f["skip"]],
            folder_path
        )
        skipped += sum(1 for f in files if f["skip"])

    if not tasks and not skipped:
        print(f"  No files found or error accessing folder")
        return 0, 0, 1

    if not tasks:
        print(f"  All {skipped} files already downloaded")
        return 0, skipped, 0

    total_size = sum(t.size for t in tasks)
    print(f"  Found {len(tasks)} files to download ({format_size(total_size)}), {skipped} already exist")
    print()

    # Download
    download_start = time.time()
    downloaded, _, errors = downloader.download_many(tasks)
    download_time = time.time() - download_start

    print(f"  Download completed in {format_duration(download_time)}")
    print(f"  Total time: {format_duration(scan_time + download_time)}")

    return downloaded, skipped, errors


def download_folders(folders: list, indices: list, download_path: str, client: DriveClient):
    """Download selected folders."""
    print()
    print("=" * 50)
    print("Starting download...")
    print(f"Destination: {download_path}")
    print("=" * 50)
    print()

    base_path = Path(download_path)
    base_path.mkdir(parents=True, exist_ok=True)

    total_downloaded = 0
    total_skipped = 0
    total_errors = 0

    for idx in indices:
        folder = folders[idx]
        print(f"\n[{folder['name']}]")
        print("-" * 40)

        downloaded, skipped, errors = sync_folder(folder, base_path, client)

        total_downloaded += downloaded
        total_skipped += skipped
        total_errors += errors

        print(f"  Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")

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
            extras = find_extra_files(folder, base_path)
            all_extras.extend(extras)

    if all_extras:
        total_extra_size = sum(size for _, size in all_extras)
        print()
        print(f"Found {len(all_extras)} local files not in manifest ({format_size(total_extra_size)})")
        print()

        # Show tree structure
        tree_lines = format_extras_tree(all_extras, base_path)
        for line in tree_lines[:10]:
            print(line)
        if len(tree_lines) > 10:
            print(f"  ... and {len(tree_lines) - 10} more folders")

        print()
        confirm = input("Remove these files? [y/N]: ").strip().lower()
        if confirm == "y":
            deleted = delete_files(all_extras, base_path)
            print(f"Removed {deleted} files ({format_size(total_extra_size)})")


# ============================================================================
# User Interface
# ============================================================================


def print_header():
    """Print application header."""
    print("=" * 50)
    print("  DM Chart Sync v2.0")
    print("  Download charts without any setup!")
    print("=" * 50)
    print()


def show_main_menu(folders: list, config: UserConfig) -> str:
    """Show main menu and get user selection."""
    print("Available chart packs:")
    print("-" * 40)

    for i, folder in enumerate(folders, 1):
        prefix = "[Official]" if folder.get("official", True) else "[Custom] "
        file_count = folder.get("file_count", 0)
        total_size = folder.get("total_size", 0)
        if file_count and total_size:
            stats = f" ({file_count} files, {format_size(total_size)})"
        else:
            stats = ""
        print(f"  [{i}] {prefix} {folder['name']}{stats}")

    print()
    print(f"  [A] Download ALL")
    print(f"  [X] Purge extra files (clean up)")
    print(f"  [C] Add custom folder")
    if config.custom_folders:
        print(f"  [R] Remove custom folder")
    print(f"  [P] Change download path (current: {config.download_path})")
    print(f"  [Q] Quit")
    print()

    return input("Enter selection: ").strip().upper()


def add_custom_folder(config: UserConfig, client: DriveClient) -> bool:
    """Prompt user to add a custom folder."""
    print("\n" + "-" * 40)
    print("Add Custom Folder")
    print("-" * 40)
    print("Paste a Google Drive folder URL or ID.")
    print("Example: https://drive.google.com/drive/folders/1ABC123xyz")
    print()

    url_or_id = input("Folder URL or ID (or 'cancel'): ").strip()
    if url_or_id.lower() == "cancel":
        return False

    folder_id = extract_folder_id(url_or_id)
    if not folder_id:
        print("Error: Invalid folder URL or ID")
        input("Press Enter to continue...")
        return False

    # Check for duplicates
    if config.get_custom_folder(folder_id):
        print("This folder is already in your list!")
        input("Press Enter to continue...")
        return False

    name = input("Give this folder a name: ").strip()
    if not name:
        name = f"Custom Folder ({folder_id[:8]}...)"

    # Verify access
    print(f"\nVerifying access to folder...")
    files = client.list_folder(folder_id)
    if not files:
        print("Error: Could not access folder. Make sure it's shared as 'Anyone with link'")
        input("Press Enter to continue...")
        return False

    print(f"Success! Found {len(files)} items in folder.")

    config.add_custom_folder(name, folder_id)
    config.save()
    print(f"Added '{name}' to your folders!")
    input("Press Enter to continue...")
    return True


def remove_custom_folder(config: UserConfig) -> bool:
    """Prompt user to remove a custom folder."""
    if not config.custom_folders:
        print("No custom folders to remove.")
        input("Press Enter to continue...")
        return False

    print("\n" + "-" * 40)
    print("Remove Custom Folder")
    print("-" * 40)

    for i, folder in enumerate(config.custom_folders, 1):
        print(f"  [{i}] {folder.name}")
    print(f"  [C] Cancel")
    print()

    choice = input("Select folder to remove: ").strip().upper()
    if choice == "C":
        return False

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(config.custom_folders):
            removed = config.custom_folders[idx]
            config.remove_custom_folder(removed.folder_id)
            config.save()
            print(f"Removed '{removed.name}'")
            input("Press Enter to continue...")
            return True
    except ValueError:
        pass

    print("Invalid selection")
    input("Press Enter to continue...")
    return False


def change_download_path(config: UserConfig):
    """Change the download directory."""
    print("\n" + "-" * 40)
    print("Change Download Path")
    print("-" * 40)
    print(f"Current path: {config.download_path}")
    print()

    new_path = input("Enter new path (or 'cancel'): ").strip()
    if new_path.lower() == "cancel":
        return

    if new_path:
        config.download_path = new_path
        config.save()
        print(f"Download path changed to: {new_path}")

    input("Press Enter to continue...")


# ============================================================================
# Main
# ============================================================================


def main():
    """Main application loop."""
    clear_screen()
    print_header()

    print("Fetching folder list...")
    manifest_data = fetch_manifest()
    config = UserConfig.load()

    # Initialize client
    client_config = DriveClientConfig(api_key=API_KEY)
    client = DriveClient(client_config)

    # Mark official folders
    for folder in manifest_data.get("folders", []):
        folder["official"] = True

    while True:
        clear_screen()
        print_header()

        # Combine official and custom folders
        all_folders = manifest_data.get("folders", []) + [
            {
                "name": f.name,
                "folder_id": f.folder_id,
                "description": f.description,
                "official": False,
            }
            for f in config.custom_folders
        ]

        if not all_folders:
            print("No folders available!")
            print("Use [C] to add a custom folder.")
            print()

        choice = show_main_menu(all_folders, config)

        if choice == "Q":
            print("\nGoodbye!")
            break

        elif choice == "A" and all_folders:
            download_folders(all_folders, list(range(len(all_folders))),
                           config.download_path, client)
            input("\nPress Enter to continue...")

        elif choice == "X":
            # Purge extra files
            print("\n" + "-" * 40)
            print("Purge Extra Files")
            print("-" * 40)
            print("Select folder to purge (removes files not in manifest):")
            for i, folder in enumerate(all_folders, 1):
                if folder.get("official"):
                    print(f"  [{i}] {folder['name']}")
            print(f"  [A] All official folders")
            print(f"  [C] Cancel")
            print()

            purge_choice = input("Selection: ").strip().upper()
            if purge_choice == "C":
                pass
            elif purge_choice == "A":
                base_path = Path(config.download_path)
                for folder in all_folders:
                    if folder.get("official"):
                        print(f"\n[{folder['name']}]")
                        purge_extra_files(folder, base_path)
                input("\nPress Enter to continue...")
            elif purge_choice.isdigit():
                idx = int(purge_choice) - 1
                if 0 <= idx < len(all_folders) and all_folders[idx].get("official"):
                    print(f"\n[{all_folders[idx]['name']}]")
                    purge_extra_files(all_folders[idx], Path(config.download_path))
                    input("\nPress Enter to continue...")

        elif choice == "C":
            add_custom_folder(config, client)

        elif choice == "R":
            remove_custom_folder(config)

        elif choice == "P":
            change_download_path(config)

        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(all_folders):
                download_folders(all_folders, [idx], config.download_path, client)
                input("\nPress Enter to continue...")
            else:
                print("Invalid selection")
                input("Press Enter to continue...")

        else:
            # Handle comma-separated selections
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                valid_indices = [i for i in indices if 0 <= i < len(all_folders)]
                if valid_indices:
                    download_folders(all_folders, valid_indices, config.download_path, client)
                    input("\nPress Enter to continue...")
                else:
                    print("Invalid selection")
                    input("Press Enter to continue...")
            except ValueError:
                print("Invalid selection")
                input("Press Enter to continue...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
