#!/usr/bin/env python3
"""
DM Chart Sync - Manifest Generator (Admin Only)

Generates the manifest.json file containing the complete file tree.
Supports incremental updates via Google Drive Changes API.
"""

import os
import sys
import time
import argparse
from pathlib import Path

# Load .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

from src.drive import DriveClient, FolderScanner, OAuthManager, ChangeTracker
from src.drive.client import DriveClientConfig
from src.manifest import Manifest, FolderEntry, count_charts_in_files
from src.config import DrivesConfig
from src.core.formatting import format_size, format_duration
from src.ui.primitives import print_progress

# ============================================================================
# Configuration
# ============================================================================

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MANIFEST_PATH = Path(__file__).parent / "manifest.json"
DRIVES_PATH = Path(__file__).parent / "drives.json"


def load_root_folders() -> list[dict]:
    """Load root folders from drives.json."""
    if not DRIVES_PATH.exists():
        print(f"Warning: drives.json not found at {DRIVES_PATH}")
        print("Using empty folder list. Create drives.json to define drives.")
        return []

    drives_config = DrivesConfig.load(DRIVES_PATH)
    return drives_config.to_root_folders_list()

# ============================================================================
# Full Scan Mode
# ============================================================================


def generate_full(force_rescan: bool = False):
    """
    Generate manifest by scanning all folders.

    Args:
        force_rescan: If True, ignore existing manifest
    """
    print("=" * 60)
    print("DM Chart Sync - Manifest Generator")
    print("=" * 60)
    print()

    # Load root folders from drives.json
    root_folders = load_root_folders()
    if not root_folders:
        print("No folders to scan. Exiting.")
        return

    expected_ids = {f["folder_id"] for f in root_folders}

    # Initialize
    client_config = DriveClientConfig(api_key=API_KEY)
    client = DriveClient(client_config)
    scanner = FolderScanner(client)

    # Load or create manifest
    if force_rescan:
        manifest = Manifest(MANIFEST_PATH)
        print("Force rescan: Starting fresh\n")
    else:
        manifest = Manifest.load(MANIFEST_PATH)

        # Remove drives that are no longer in drives.json
        orphaned_ids = manifest.get_folder_ids() - expected_ids
        if orphaned_ids:
            for orphan_id in orphaned_ids:
                folder = manifest.get_folder(orphan_id)
                if folder:
                    print(f"Removing '{folder.name}' (no longer in drives.json)")
                manifest.remove_folder(orphan_id)
            manifest.save()
            print()

        complete_ids = manifest.get_complete_folder_ids()
        incomplete_ids = manifest.get_incomplete_folder_ids()
        if complete_ids or incomplete_ids:
            status_parts = []
            if complete_ids:
                status_parts.append(f"{len(complete_ids)} complete")
            if incomplete_ids:
                status_parts.append(f"{len(incomplete_ids)} incomplete")
            print(f"Resuming: {', '.join(status_parts)}\n")

    complete_ids = manifest.get_complete_folder_ids()

    was_cancelled = False

    for i, folder_info in enumerate(root_folders, 1):
        folder_id = folder_info["folder_id"]

        # Skip if already fully scanned (incomplete drives get re-scanned)
        if folder_id in complete_ids and not force_rescan:
            print(f"[{i}/{len(root_folders)}] {folder_info['name']} - SKIPPED (complete)")
            print()
            continue

        print(f"[{i}/{len(root_folders)}] {folder_info['name']}")
        print("-" * 40)

        start_time = time.time()
        start_api_calls = client.api_calls

        # Progress callback with periodic chart counting
        last_chart_count = [0]
        def progress(folders, files, shortcuts, files_list):
            # Count charts periodically (every 500 files to avoid slowdown)
            if files % 500 == 0 or files < 100:
                stats = count_charts_in_files(files_list)
                last_chart_count[0] = stats.chart_counts.total

            shortcut_info = f", {shortcuts} shortcuts" if shortcuts else ""
            print_progress(f"[{client.api_calls} API] {folders} folders, {files} files, ~{last_chart_count[0]} charts{shortcut_info}")

        result = scanner.scan(folder_id, "", progress)
        print()

        elapsed = time.time() - start_time
        calls_used = client.api_calls - start_api_calls
        folder_size = sum(f["size"] for f in result.files)

        # Count charts
        drive_stats = count_charts_in_files(result.files)

        # Update manifest (even if cancelled - save partial progress)
        folder_entry = FolderEntry(
            name=folder_info["name"],
            folder_id=folder_id,
            description=folder_info["description"],
            file_count=len(result.files),
            total_size=folder_size,
            files=result.files,
            chart_count=drive_stats.chart_counts.total,
            charts=drive_stats.chart_counts.to_dict(),
            subfolders=[sf.to_dict() for sf in drive_stats.subfolders.values()],
            complete=not result.cancelled,  # Mark incomplete if interrupted
        )
        manifest.add_folder(folder_entry)
        manifest.save()

        print(f"  {len(result.files)} files ({format_size(folder_size)})")
        print(f"  {drive_stats.chart_counts.total} charts ({drive_stats.chart_counts.folder} folder, {drive_stats.chart_counts.zip} zip, {drive_stats.chart_counts.sng} sng)")
        if drive_stats.subfolders:
            print(f"  {len(drive_stats.subfolders)} subfolders")
        print(f"  {calls_used} API calls in {format_duration(elapsed)}")
        if result.cancelled:
            print(f"  PARTIAL SCAN SAVED to manifest.json")
        else:
            print(f"  SAVED to manifest.json")
        print()

        # If scan was cancelled, stop processing more folders
        if result.cancelled:
            was_cancelled = True
            print("Stopping - partial progress has been saved.")
            print("Run again to continue from where you left off.\n")
            break

    # Save changes token for incremental updates (only if not cancelled)
    if not was_cancelled:
        auth = OAuthManager()
        if auth.is_available and auth.is_configured:
            print("Saving changes token for incremental updates...")
            try:
                token = auth.get_token()
                if token:
                    oauth_client = DriveClient(client_config, auth_token=token)
                    manifest.changes_token = oauth_client.get_changes_start_token()
                    manifest.save()
                    print(f"  Token saved! Use default mode for future updates.")
                else:
                    print("  Skipped (OAuth not configured)")
            except Exception as e:
                print(f"  Warning: Could not save token: {e}")
            print()

    # Summary
    print("=" * 60)
    if was_cancelled:
        print("Summary (PARTIAL - scan was interrupted)")
    else:
        print("Summary")
    print("=" * 60)
    print(f"  Drives in manifest: {len(manifest.folders)}")
    print(f"  Total files: {manifest.total_files}")
    print(f"  Total size: {format_size(manifest.total_size)}")
    total_charts = sum(f.chart_count for f in manifest.folders)
    print(f"  Total charts: {total_charts}")
    print(f"  Total API calls: {client.api_calls}")
    print(f"  Manifest size: {format_size(MANIFEST_PATH.stat().st_size)}")
    if was_cancelled:
        print()
        print("  Run again without --force to resume scanning.")
    print()


# ============================================================================
# Shortcut Folder Tracking
# ============================================================================

SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
FOLDER_MIME = "application/vnd.google-apps.folder"


def find_shortcuts_in_folder(client: DriveClient, folder_id: str) -> list[dict]:
    """
    Find all shortcut folders in a folder's immediate children.

    Returns list of {shortcut_id, target_id, name}
    """
    shortcuts = []
    items = client.list_folder(folder_id)

    for item in items:
        if item.get("mimeType") == SHORTCUT_MIME:
            details = item.get("shortcutDetails", {})
            target_mime = details.get("targetMimeType", "")
            # Only track shortcuts to folders
            if target_mime == FOLDER_MIME:
                shortcuts.append({
                    "shortcut_id": item.get("id"),
                    "target_id": details.get("targetId"),
                    "name": item.get("name"),
                })

    return shortcuts


def check_shortcut_folders(
    client: DriveClient,
    manifest: Manifest,
    root_folders: list[dict],
) -> list[dict]:
    """
    Check all shortcut folders for changes.

    Returns list of shortcuts that need rescanning:
    [{shortcut_id, target_id, name, parent_folder_id, parent_name}]
    """
    changed = []

    for folder_info in root_folders:
        folder_id = folder_info["folder_id"]
        folder_name = folder_info["name"]

        # Find shortcuts in this folder
        shortcuts = find_shortcuts_in_folder(client, folder_id)

        for sc in shortcuts:
            shortcut_id = sc["shortcut_id"]
            target_id = sc["target_id"]

            # Get target folder's current modifiedTime
            target_meta = client.get_file_metadata(
                target_id,
                fields="id,modifiedTime"
            )
            if not target_meta:
                continue

            current_modified = target_meta.get("modifiedTime", "")

            # Check if we have this shortcut tracked
            stored = manifest.shortcut_folders.get(shortcut_id)

            if stored:
                # Already tracked - check if modified since last scan
                stored_modified = stored.get("last_modified", "")
                if current_modified != stored_modified:
                    changed.append({
                        "shortcut_id": shortcut_id,
                        "target_id": target_id,
                        "name": sc["name"],
                        "parent_folder_id": folder_id,
                        "parent_name": folder_name,
                        "current_modified": current_modified,
                    })
            # If not tracked yet, just record it (don't trigger rescan)

            # Update stored info (even if not changed, ensures we track all)
            manifest.shortcut_folders[shortcut_id] = {
                "target_id": target_id,
                "name": sc["name"],
                "parent_folder_id": folder_id,
                "last_modified": current_modified,
            }

    return changed


def rescan_shortcut_folder(
    client: DriveClient,
    scanner: FolderScanner,
    manifest: Manifest,
    shortcut_info: dict,
) -> tuple[int, int, int]:
    """
    Rescan a single shortcut folder and update manifest.

    Returns (added, modified, removed) counts.
    """
    target_id = shortcut_info["target_id"]
    shortcut_name = shortcut_info["name"]
    parent_folder_id = shortcut_info["parent_folder_id"]

    # Get the parent folder entry from manifest
    parent_folder = manifest.get_folder(parent_folder_id)
    if not parent_folder:
        return 0, 0, 0

    # Build prefix path for files under this shortcut
    prefix = shortcut_name

    # Scan the target folder
    result = scanner.scan(target_id, prefix)

    # Build lookup of existing files under this shortcut path
    existing_paths = {}
    for i, f in enumerate(parent_folder.files):
        path = f.get("path") if isinstance(f, dict) else f.path
        if path.startswith(prefix + "/") or path == prefix:
            existing_paths[path] = i

    # Track changes
    added = 0
    modified = 0
    new_files = []
    seen_paths = set()

    for new_file in result.files:
        path = new_file.get("path", "")
        seen_paths.add(path)

        if path in existing_paths:
            # Check if modified
            old_idx = existing_paths[path]
            old_file = parent_folder.files[old_idx]
            old_md5 = old_file.get("md5") if isinstance(old_file, dict) else old_file.md5
            new_md5 = new_file.get("md5", "")

            if old_md5 != new_md5:
                parent_folder.files[old_idx] = new_file
                modified += 1
        else:
            new_files.append(new_file)
            added += 1

    # Find removed files
    removed = 0
    indices_to_remove = []
    for path, idx in existing_paths.items():
        if path not in seen_paths:
            indices_to_remove.append(idx)
            removed += 1

    # Remove in reverse order to preserve indices
    for idx in sorted(indices_to_remove, reverse=True):
        parent_folder.files.pop(idx)

    # Add new files
    parent_folder.files.extend(new_files)

    # Update counts
    parent_folder.file_count = len(parent_folder.files)
    parent_folder.total_size = sum(
        f.get("size", 0) if isinstance(f, dict) else f.size
        for f in parent_folder.files
    )

    return added, modified, removed


# ============================================================================
# Incremental Mode (Changes API)
# ============================================================================


def generate_incremental():
    """Update manifest using Changes API (requires OAuth)."""
    print("=" * 60)
    print("DM Chart Sync - Incremental Manifest Update")
    print("=" * 60)
    print()

    # Check OAuth
    auth = OAuthManager()
    if not auth.is_available:
        print("ERROR: OAuth libraries not installed.")
        print("Run: pip install google-auth google-auth-oauthlib")
        sys.exit(1)

    if not auth.is_configured:
        print("ERROR: credentials.json not found.")
        print()
        print("To use incremental mode, you need to set up OAuth:")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create OAuth 2.0 Client ID (Desktop app)")
        print("3. Download JSON and save as 'credentials.json' in this folder")
        print()
        print("Alternatively, run with --full for a full scan (API key only).")
        sys.exit(1)

    # Authenticate
    print("Authenticating with Google...")
    token = auth.get_token()
    if not token:
        print("ERROR: OAuth authentication failed.")
        sys.exit(1)
    print("  Authenticated successfully!")
    print()

    # Load manifest
    manifest = Manifest.load(MANIFEST_PATH)

    # Load root folders to check if all drives have been scanned
    root_folders = load_root_folders()
    expected_ids = {f["folder_id"] for f in root_folders}

    # Remove drives that are no longer in drives.json
    orphaned_ids = manifest.get_folder_ids() - expected_ids
    if orphaned_ids:
        for orphan_id in orphaned_ids:
            folder = manifest.get_folder(orphan_id)
            if folder:
                print(f"Removing '{folder.name}' (no longer in drives.json)")
            manifest.remove_folder(orphan_id)
        manifest.save()
        print()

    complete_ids = manifest.get_complete_folder_ids()

    # Check if manifest is incomplete - need full scan first
    missing_drives = expected_ids - manifest.get_folder_ids()
    # Drives not in complete_ids (includes 0-file drives)
    incomplete_drives = expected_ids - complete_ids

    if not manifest.folders or not manifest.changes_token or missing_drives or incomplete_drives:
        if not manifest.folders:
            print("No manifest found - starting full scan...")
        elif missing_drives:
            print(f"Incomplete manifest ({len(missing_drives)} drives not scanned) - continuing full scan...")
        elif incomplete_drives:
            print(f"Incomplete manifest ({len(incomplete_drives)} drives partially scanned) - continuing full scan...")
        else:
            print("No changes token found - starting full scan...")
        print()
        generate_full(force_rescan=False)
        return

    # Apply changes from Changes API (catches directly owned files)
    print("Checking for changes (owned files)...")
    start_time = time.time()

    client_config = DriveClientConfig(api_key=API_KEY)
    client = DriveClient(client_config, auth_token=token)
    tracker = ChangeTracker(client, manifest)

    try:
        stats = tracker.apply_changes(expected_ids)
    except Exception as e:
        print(f"ERROR: Could not fetch changes: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time
    print(f"  Processed in {format_duration(elapsed)} ({stats.api_calls} API calls)")

    if stats.added > 0 or stats.modified > 0 or stats.removed > 0:
        print(f"  Changes: +{stats.added} -{stats.removed} ~{stats.modified}")
    print()

    # Check shortcut folders for changes (catches external/shared files)
    print("Checking shortcut folders for changes...")
    start_api = client.api_calls
    changed_shortcuts = check_shortcut_folders(client, manifest, root_folders)
    shortcut_api_calls = client.api_calls - start_api

    total_sc_added = 0
    total_sc_modified = 0
    total_sc_removed = 0

    if changed_shortcuts:
        print(f"  Found {len(changed_shortcuts)} folder(s) with changes")
        scanner = FolderScanner(client)

        for sc in changed_shortcuts:
            print(f"  Rescanning: {sc['parent_name']}/{sc['name']}...")
            sc_added, sc_modified, sc_removed = rescan_shortcut_folder(
                client, scanner, manifest, sc
            )
            total_sc_added += sc_added
            total_sc_modified += sc_modified
            total_sc_removed += sc_removed
            if sc_added or sc_modified or sc_removed:
                print(f"    +{sc_added} -{sc_removed} ~{sc_modified}")

        # Update shortcut timestamps after successful rescan
        for sc in changed_shortcuts:
            manifest.shortcut_folders[sc["shortcut_id"]]["last_modified"] = sc["current_modified"]
    else:
        print(f"  No shortcut folder changes ({shortcut_api_calls} API calls)")
    print()

    # Combine totals
    total_added = stats.added + total_sc_added
    total_modified = stats.modified + total_sc_modified
    total_removed = stats.removed + total_sc_removed
    total_api = client.api_calls

    if total_added == 0 and total_modified == 0 and total_removed == 0:
        print("No changes detected!")
        manifest.save()
        print(f"  Token updated. Total API calls: {total_api}")
        return

    # Save manifest
    manifest.save()

    # Summary
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Added: {total_added} files")
    print(f"  Removed: {total_removed} files")
    print(f"  Modified: {total_modified} files")
    if stats.skipped:
        print(f"  Skipped: {stats.skipped} (not in tracked folders)")
    print(f"  Total API calls: {total_api}")
    print()


# ============================================================================
# CLI
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Generate manifest for DM Chart Sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python manifest_gen.py          # Incremental update (default, ~1 API call)
  python manifest_gen.py --full   # Full scan with resume support
  python manifest_gen.py --force  # Force complete rescan (~16k API calls)

First-time OAuth setup (automatic on first run):
  Browser opens for Google sign-in, token saved for future runs.
"""
    )
    parser.add_argument("--full", action="store_true",
                        help="Full folder scan (with resume support)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Force complete rescan (ignore existing manifest)")
    args = parser.parse_args()

    if args.force:
        generate_full(force_rescan=True)
    elif args.full:
        generate_full(force_rescan=False)
    else:
        generate_incremental()


if __name__ == "__main__":
    main()
