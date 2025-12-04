#!/usr/bin/env python3
"""Raw file stats - NO src imports, works even if imports are broken."""

import os
import sys
from pathlib import Path


def fmt_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/raw_stats.py <path>")
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: {path} does not exist")
        return 1

    print(f"Raw stats for: {path}")
    print("=" * 70)

    total_files = 0
    total_size = 0
    chart_folders = 0

    chart_markers = {"song.ini", "notes.mid", "notes.chart"}
    archive_exts = {".zip", ".rar", ".7z"}

    for root, _, files in os.walk(path):
        has_marker = False
        for f in files:
            total_files += 1
            try:
                total_size += (Path(root) / f).stat().st_size
            except OSError:
                pass
            f_lower = f.lower()
            if f_lower in chart_markers or any(f_lower.endswith(ext) for ext in archive_exts):
                has_marker = True
        if has_marker:
            chart_folders += 1

    print(f"\nTotal: {chart_folders} charts, {total_files} files, {fmt_size(total_size)}")

    print(f"\nSubfolders:")
    print("-" * 70)
    for subfolder in sorted(path.iterdir()):
        if subfolder.is_dir():
            sub_files = sub_size = sub_charts = 0
            for root, _, files in os.walk(subfolder):
                has_marker = False
                for f in files:
                    sub_files += 1
                    try:
                        sub_size += (Path(root) / f).stat().st_size
                    except OSError:
                        pass
                    f_lower = f.lower()
                    if f_lower in chart_markers or any(f_lower.endswith(ext) for ext in archive_exts):
                        has_marker = True
                if has_marker:
                    sub_charts += 1
            print(f"  {subfolder.name}: {sub_charts} charts, {sub_files} files, {fmt_size(sub_size)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
