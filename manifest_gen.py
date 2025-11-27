#!/usr/bin/env python3
"""
DM Chart Sync - Manifest Generator (Admin Only)

Generates the manifest.json file containing the complete file tree.
Supports incremental updates via Google Drive Changes API.
"""

import sys
import time
import argparse
from pathlib import Path

from src import (
    DriveClient,
    Manifest,
    FolderScanner,
    OAuthManager,
    ChangeTracker,
    format_size,
    format_duration,
    print_progress,
)
from src.drive_client import DriveClientConfig
from src.manifest import FolderEntry

# ============================================================================
# Configuration
# ============================================================================

API_KEY = "REDACTED_API_KEY"
MANIFEST_PATH = Path(__file__).parent / "manifest.json"

# Root folders to scan
ROOT_FOLDERS = [
    {
        "name": "BirdmanExe",
        "folder_id": "1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf",
        "description": "BirdmanExe's chart collection",
    },
    {
        "name": "Drummer's Monthly",
        "folder_id": "1bqsJzbXRkmRda3qJFX3W36UD3Sg_eIVj",
        "description": "Official Drummer's Monthly charts",
    },
    {
        "name": "DM Meme Drive",
        "folder_id": "1DuAZ36Fn_T7f_tD2Ak84Q87xZgxwn1gY",
        "description": "Meme charts and fun stuff",
    },
]

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
        existing = manifest.get_folder_ids()
        if existing:
            print(f"Resuming: {len(existing)} folders already scanned\n")

    scanned_ids = manifest.get_folder_ids()

    for i, folder_info in enumerate(ROOT_FOLDERS, 1):
        folder_id = folder_info["folder_id"]

        # Skip if already scanned
        if folder_id in scanned_ids and not force_rescan:
            print(f"[{i}/{len(ROOT_FOLDERS)}] {folder_info['name']} - SKIPPED (already in manifest)")
            print()
            continue

        print(f"[{i}/{len(ROOT_FOLDERS)}] {folder_info['name']}")
        print("-" * 40)

        start_time = time.time()
        start_api_calls = client.api_calls

        # Progress callback
        def progress(folders, files, shortcuts):
            shortcut_info = f", {shortcuts} shortcuts" if shortcuts else ""
            print_progress(f"[{client.api_calls} API calls] {folders} folders, {files} files{shortcut_info}")

        result = scanner.scan(folder_id, "", progress)
        print()

        elapsed = time.time() - start_time
        calls_used = client.api_calls - start_api_calls
        folder_size = sum(f["size"] for f in result.files)

        # Update manifest
        folder_entry = FolderEntry(
            name=folder_info["name"],
            folder_id=folder_id,
            description=folder_info["description"],
            file_count=len(result.files),
            total_size=folder_size,
            files=result.files,
        )
        manifest.add_folder(folder_entry)
        manifest.save()

        print(f"  {len(result.files)} files ({format_size(folder_size)})")
        print(f"  {calls_used} API calls in {format_duration(elapsed)}")
        print(f"  SAVED to manifest.json")
        print()

    # Save changes token for incremental updates
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
    print("Summary")
    print("=" * 60)
    print(f"  Folders in manifest: {len(manifest.folders)}")
    print(f"  Total files: {manifest.total_files}")
    print(f"  Total size: {format_size(manifest.total_size)}")
    print(f"  Total API calls: {client.api_calls}")
    print(f"  Manifest size: {format_size(MANIFEST_PATH.stat().st_size)}")
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

    # Check for saved token
    if not manifest.changes_token:
        print("No saved token found - need to do initial full scan first.")
        print("Run with --full to do a full scan, then use default mode for updates.")
        print()
        print("Or, saving current token for future incremental updates...")

        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config, auth_token=token)
        manifest.changes_token = client.get_changes_start_token()
        manifest.save()

        print(f"  Token saved! Next run will detect changes.")
        print(f"  API calls: {client.api_calls}")
        return

    # Apply changes
    print("Fetching changes since last update...")
    start_time = time.time()

    client_config = DriveClientConfig(api_key=API_KEY)
    client = DriveClient(client_config, auth_token=token)
    tracker = ChangeTracker(client, manifest)

    tracked_ids = {f["folder_id"] for f in ROOT_FOLDERS}

    try:
        stats = tracker.apply_changes(tracked_ids)
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

    try:
        if args.force:
            generate_full(force_rescan=True)
        elif args.full:
            generate_full(force_rescan=False)
        else:
            generate_incremental()
    except KeyboardInterrupt:
        print("\n\nCancelled. Progress has been saved.")
        sys.exit(1)


if __name__ == "__main__":
    main()
