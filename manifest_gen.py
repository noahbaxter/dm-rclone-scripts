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

from src import (
    DriveClient,
    Manifest,
    FolderScanner,
    OAuthManager,
    ChangeTracker,
    DrivesConfig,
    format_size,
    format_duration,
    print_progress,
)
from src.drive.client import DriveClientConfig
from src.manifest import FolderEntry
from src.charts import count_charts_in_files

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

    # Apply changes
    print("Fetching changes since last update...")
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
    print()

    if stats.added == 0 and stats.modified == 0 and stats.removed == 0:
        print("No changes detected!")
        manifest.save()
        print(f"  Token updated. Total API calls: {stats.api_calls}")
        return

    # Save manifest
    manifest.save()

    # Summary
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Added: {stats.added} files")
    print(f"  Removed: {stats.removed} files")
    print(f"  Modified: {stats.modified} files")
    print(f"  Skipped: {stats.skipped} (not in tracked folders)")
    print(f"  Total API calls: {stats.api_calls}")
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
