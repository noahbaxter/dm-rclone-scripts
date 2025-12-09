#!/usr/bin/env python3
"""Trace through count_purgeable_files logic step by step."""

import sys
from pathlib import Path
from _helpers import REPO_ROOT, fetch_manifest, find_folder_in_manifest, load_settings_from_sync_path

sys.path.insert(0, str(REPO_ROOT))

from src.utils import format_size
from src.sync import count_purgeable_detailed
from src.sync.cache import scan_local_files, scan_actual_charts
from src.sync.purge_planner import find_extra_files, find_partial_downloads

# Backwards compat
_scan_local_files = scan_local_files
_scan_actual_charts = scan_actual_charts
from src.stats import get_best_stats


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/trace_purgeable.py <path_to_drive_folder>")
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: {path} does not exist")
        return 1

    manifest = fetch_manifest()
    folder = find_folder_in_manifest(manifest, path.name)
    settings = load_settings_from_sync_path(path)
    folder_id = folder.get("folder_id", "")

    print(f"\nTracing count_purgeable_files for: {path}")
    print("=" * 70)

    # Basic info
    manifest_files = folder.get("files", [])
    disabled_setlists = settings.get_disabled_subfolders(folder_id)
    drive_enabled = settings.is_drive_enabled(folder_id)

    print(f"\nDRIVE ENABLED: {drive_enabled}")
    print(f"DISABLED SETLISTS: {disabled_setlists}")
    print(f"MANIFEST FILES: {len(manifest_files)}")

    # Step 1: Call actual count_purgeable_detailed for full breakdown
    print(f"\n" + "=" * 70)
    print("STEP 1: ACTUAL count_purgeable_detailed RESULT")
    print("=" * 70)
    stats = count_purgeable_detailed([folder], path.parent, settings)
    print(f"  Chart files:   {stats.chart_count} files, {format_size(stats.chart_size)}")
    print(f"  Extra files:   {stats.extra_file_count} files, {format_size(stats.extra_file_size)}")
    print(f"  Partial files: {stats.partial_count} files, {format_size(stats.partial_size)}")
    print(f"  TOTAL:         {stats.total_files} files, {format_size(stats.total_size)}")

    # Step 2: Scan local files
    print(f"\n" + "=" * 70)
    print("STEP 2: LOCAL FILE SCAN")
    print("=" * 70)
    local_files = _scan_local_files(path)
    print(f"  Total local files: {len(local_files)}")

    # Step 3: Per-setlist breakdown (disabled only)
    print(f"\n" + "=" * 70)
    print("STEP 3: DISABLED SETLIST BREAKDOWN")
    print("=" * 70)
    for setlist_name in sorted(disabled_setlists):
        setlist_path = path / setlist_name
        if setlist_path.exists():
            file_count = sum(1 for f in setlist_path.rglob("*") if f.is_file())
            size = sum(f.stat().st_size for f in setlist_path.rglob("*") if f.is_file())
            charts, chart_size = _scan_actual_charts(setlist_path, set())
            print(f"  {setlist_name}:")
            print(f"    Files on disk: {file_count} ({format_size(size)})")
            print(f"    Chart folders: {charts} ({format_size(chart_size)})")
        else:
            print(f"  {setlist_name}: NOT ON DISK")

    # Step 4: Extra files (not in manifest)
    print(f"\n" + "=" * 70)
    print("STEP 4: EXTRA FILES (find_extra_files)")
    print("=" * 70)
    extras = find_extra_files(folder, path.parent)
    if extras:
        print(f"  Found {len(extras)} extra files:")
        for f, size in extras[:10]:  # Show first 10
            rel = f.relative_to(path.parent)
            print(f"    {rel} ({format_size(size)})")
        if len(extras) > 10:
            print(f"    ... and {len(extras) - 10} more")
    else:
        print(f"  No extra files found")

    # Step 5: Partial downloads
    print(f"\n" + "=" * 70)
    print("STEP 5: PARTIAL DOWNLOADS")
    print("=" * 70)
    partials = find_partial_downloads(path.parent)
    if partials:
        print(f"  Found {len(partials)} partial downloads:")
        for f, size in partials:
            print(f"    {f.name} ({format_size(size)})")
    else:
        print(f"  No partial downloads found")

    # Step 6: get_best_stats for each disabled setlist
    print(f"\n" + "=" * 70)
    print("STEP 6: get_best_stats FOR DISABLED SETLISTS")
    print("=" * 70)
    for setlist_name in sorted(disabled_setlists):
        sf_data = next((sf for sf in folder.get("subfolders", []) if sf.get("name") == setlist_name), {})
        manifest_charts = sf_data.get("charts", {}).get("total", 0)
        manifest_size = sf_data.get("total_size", 0)

        best_charts, best_size = get_best_stats(
            folder_name=path.name,
            setlist_name=setlist_name,
            manifest_charts=manifest_charts,
            manifest_size=manifest_size,
            local_path=path if path.exists() else None,
        )
        print(f"  {setlist_name}: {best_charts} charts, {format_size(best_size)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
