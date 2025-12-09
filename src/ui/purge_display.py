"""
Purge display formatting for DM Chart Sync.

Handles rendering purge file trees and stats.
"""

from collections import defaultdict
from pathlib import Path
from typing import List, Tuple

from ..utils import format_size


def format_purge_tree(files: List[Tuple[Path, int]], base_path: Path) -> List[str]:
    """
    Format files to purge as a tree showing file counts per folder.

    Args:
        files: List of (Path, size) tuples
        base_path: Base path for relative display

    Returns list of formatted strings to print.
    """
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
