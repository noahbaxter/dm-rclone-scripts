"""
File deletion (purging) for DM Chart Sync.

Handles deleting files and cleaning up empty directories.
"""

import stat
from pathlib import Path
from typing import List, Tuple


def _fix_path_permissions(path: Path) -> bool:
    """Try to make a file/folder writable. Returns True if successful."""
    try:
        mode = path.stat().st_mode
        if not (mode & stat.S_IWUSR):
            path.chmod(mode | stat.S_IWUSR)
        # Also fix parent folder if needed
        parent = path.parent
        parent_mode = parent.stat().st_mode
        if not (parent_mode & stat.S_IWUSR):
            parent.chmod(parent_mode | stat.S_IWUSR)
        return True
    except (OSError, PermissionError):
        return False


def delete_files(files: List[Tuple[Path, int]], base_path: Path) -> Tuple[int, int]:
    """
    Delete files and clean up empty directories.

    Args:
        files: List of (Path, size) tuples
        base_path: Base path to clean empty dirs under

    Returns tuple of (deleted_count, failed_count).
    """
    deleted = 0
    failed = 0

    for f, _ in files:
        try:
            f.unlink()
            deleted += 1
        except PermissionError:
            # Try fixing permissions and retry
            if _fix_path_permissions(f):
                try:
                    f.unlink()
                    deleted += 1
                    continue
                except Exception:
                    pass
            failed += 1
        except Exception:
            failed += 1

    # Clean up empty directories (fix permissions as needed)
    try:
        for d in sorted(base_path.rglob("*"), reverse=True):
            if d.is_dir():
                try:
                    if not any(d.iterdir()):
                        d.rmdir()
                except PermissionError:
                    _fix_path_permissions(d)
                    try:
                        if not any(d.iterdir()):
                            d.rmdir()
                    except Exception:
                        pass
                except Exception:
                    pass
    except Exception:
        pass

    return deleted, failed
