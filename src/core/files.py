"""
File system utilities for DM Chart Sync.
"""

from pathlib import Path
from typing import Set, List, Tuple


def file_exists_with_size(path: Path, expected_size: int) -> bool:
    """Check if file exists and matches expected size."""
    if not path.exists():
        return False
    try:
        return path.stat().st_size == expected_size
    except Exception:
        return False


def find_unexpected_files(folder_path: Path, expected_paths: Set[Path]) -> List[Path]:
    """
    Find local files not in the expected set.

    Args:
        folder_path: Folder to scan
        expected_paths: Set of expected file paths

    Returns:
        List of paths to unexpected files
    """
    if not folder_path.exists():
        return []

    local_files = [f for f in folder_path.rglob("*") if f.is_file()]
    return [f for f in local_files if f not in expected_paths]


def find_unexpected_files_with_sizes(folder_path: Path, expected_paths: Set[Path]) -> List[Tuple[Path, int]]:
    """
    Find local files not in the expected set, with their sizes.

    Args:
        folder_path: Folder to scan
        expected_paths: Set of expected file paths

    Returns:
        List of (path, size) tuples for unexpected files
    """
    extra_files = find_unexpected_files(folder_path, expected_paths)
    result = []
    for f in extra_files:
        try:
            result.append((f, f.stat().st_size))
        except Exception:
            result.append((f, 0))
    return result
