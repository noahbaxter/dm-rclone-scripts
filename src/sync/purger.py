"""
File deletion (purging) for DM Chart Sync.

Handles deleting files and cleaning up empty directories.
"""

from pathlib import Path
from typing import List, Tuple


def delete_files(files: List[Tuple[Path, int]], base_path: Path) -> int:
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
