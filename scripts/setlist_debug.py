#!/usr/bin/env python3
"""Debug setlist screen calculations for a drive folder."""

import sys
from pathlib import Path
from _helpers import REPO_ROOT, fetch_manifest, find_folder_in_manifest, load_settings_from_sync_path

sys.path.insert(0, str(REPO_ROOT))

from src.utils import format_size
from src.constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS
from src.ui.screens import extract_subfolders_from_manifest
from src.sync.operations import count_purgeable_files
from src.stats import get_best_stats


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/setlist_debug.py <path_to_drive_folder>")
        print("Example: python scripts/setlist_debug.py '/path/to/Sync Charts/Guitar Hero'")
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: {path} does not exist")
        return 1

    manifest = fetch_manifest()
    folder = find_folder_in_manifest(manifest, path.name)
    settings = load_settings_from_sync_path(path)
    folder_id = folder.get("folder_id", "")

    print(f"\nSetlist Debug for: {path}")
    print("=" * 70)

    # Get setlists from manifest
    setlists = extract_subfolders_from_manifest(folder)
    manifest_files = folder.get("files", [])
    disabled_setlists = settings.get_disabled_subfolders(folder_id)

    print(f"\nSETLISTS IN MANIFEST ({len(setlists)}):")
    for setlist in sorted(setlists):
        enabled = settings.is_subfolder_enabled(folder_id, setlist)
        status = "[ON] " if enabled else "[OFF]"

        # Count charts from manifest
        chart_count = sum(
            1 for f in manifest_files
            if f.get("path", "").startswith(f"{setlist}/") and (
                f.get("path", "").split("/")[-1].lower() in CHART_MARKERS or
                any(f.get("path", "").lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)
            )
        )

        exists = "EXISTS" if (path / setlist).exists() else "NOT ON DISK"
        print(f"  {status} {setlist}: {chart_count} charts [{exists}]")

    print(f"\nDISABLED SETLISTS: {disabled_setlists}")

    # What's on disk
    print(f"\nFOLDERS ON DISK:")
    for subfolder in sorted(path.iterdir()):
        if subfolder.is_dir():
            file_count = sum(1 for _ in subfolder.rglob("*") if _.is_file())
            size = sum(f.stat().st_size for f in subfolder.rglob("*") if f.is_file())
            in_disabled = subfolder.name in disabled_setlists
            status = "[DISABLED]" if in_disabled else "[ENABLED]"
            print(f"  {status} {subfolder.name}: {file_count} files, {format_size(size)}")

    # Call actual count_purgeable_files function
    print(f"\nACTUAL count_purgeable_files RESULT:")
    print("-" * 70)
    purgeable_count, purgeable_size = count_purgeable_files([folder], path.parent, settings)
    print(f"  {purgeable_count} files, {format_size(purgeable_size)}")

    # Show per-setlist breakdown
    print(f"\nPER-SETLIST BREAKDOWN (disabled only):")
    print("-" * 70)
    for setlist_name in sorted(disabled_setlists):
        setlist_path = path / setlist_name
        if setlist_path.exists():
            file_count = sum(1 for f in setlist_path.rglob("*") if f.is_file())
            size = sum(f.stat().st_size for f in setlist_path.rglob("*") if f.is_file())
            print(f"  {setlist_name}: {file_count} files, {format_size(size)}")
        else:
            print(f"  {setlist_name}: NOT ON DISK")

    # Show actual chart counts using get_best_stats
    print(f"\nCHART COUNTS (via get_best_stats):")
    print("-" * 70)
    for setlist in sorted(setlists):
        sf_data = next((sf for sf in folder.get("subfolders", []) if sf.get("name") == setlist), {})
        manifest_charts = sf_data.get("charts", {}).get("total", 0)
        manifest_size = sf_data.get("total_size", 0)

        best_charts, best_size = get_best_stats(
            folder_name=path.name,
            setlist_name=setlist,
            manifest_charts=manifest_charts,
            manifest_size=manifest_size,
            local_path=path if path.exists() else None,
        )

        enabled = settings.is_subfolder_enabled(folder_id, setlist)
        status = "[ON] " if enabled else "[OFF]"
        exists = "local" if (path / setlist).exists() else "manifest"
        print(f"  {status} {setlist}: {best_charts} charts ({exists})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
