#!/usr/bin/env python3
"""Scan a folder for charts using _scan_actual_charts_uncached."""

import sys
from pathlib import Path
from _helpers import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from src.sync.operations import _scan_actual_charts_uncached
from src.utils import format_size


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/scan_charts.py <path>")
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: {path} does not exist")
        return 1

    print(f"Scanning: {path}")
    print("=" * 70)

    chart_count, total_size = _scan_actual_charts_uncached(path)
    print(f"\nTotal: {chart_count} charts, {format_size(total_size)}")

    print(f"\nSubfolders:")
    print("-" * 70)
    for subfolder in sorted(path.iterdir()):
        if subfolder.is_dir():
            sub_charts, sub_size = _scan_actual_charts_uncached(subfolder)
            print(f"  {subfolder.name}: {sub_charts} charts, {format_size(sub_size)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
