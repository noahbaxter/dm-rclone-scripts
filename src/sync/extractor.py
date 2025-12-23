"""
Archive extraction for DM Chart Sync.

Handles extracting ZIP, 7z, and RAR archives with bundled tool support.
"""

import os
import sys
import zipfile
from pathlib import Path
from typing import Tuple, Set

from ..core.constants import VIDEO_EXTENSIONS
from ..core.formatting import relative_posix

# Optional archive format support
try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False


try:
    import rarfile
    HAS_RAR_LIB = True
except ImportError:
    HAS_RAR_LIB = False
    rarfile = None


def _setup_unrar_tool():
    """Configure rarfile to use bundled UnRAR command-line tool."""
    if not HAS_RAR_LIB:
        return

    tool_path = None

    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running from PyInstaller bundle
        bundle_dir = sys._MEIPASS
        if os.name == 'nt':
            tool_path = os.path.join(bundle_dir, 'UnRAR.exe')
        else:
            tool_path = os.path.join(bundle_dir, 'unrar')
    else:
        # Development mode - check for libs folder
        dev_libs = Path(__file__).parent.parent.parent / 'libs' / 'bin'
        if os.name == 'nt':
            tool_path = dev_libs / 'UnRAR.exe'
        else:
            tool_path = dev_libs / 'unrar'
        tool_path = str(tool_path) if tool_path.exists() else None

    if tool_path and os.path.exists(tool_path):
        rarfile.UNRAR_TOOL = tool_path


_setup_unrar_tool()


# Checksum file name (excluded from size calculations)
CHECKSUM_FILE = "check.txt"


def fix_permissions(folder_path: Path) -> int:
    """
    Recursively fix restrictive permissions on extracted content.

    Some archives (especially RAR) preserve restrictive Unix permissions (555).
    This causes issues with reading/moving/deleting extracted content.

    Returns count of items fixed.
    """
    import stat
    fixed = 0
    # Permissions we need: read + write for owner
    needed = stat.S_IRUSR | stat.S_IWUSR
    try:
        for root, dirs, files in os.walk(folder_path):
            for d in dirs:
                dp = Path(root) / d
                try:
                    mode = dp.stat().st_mode
                    if (mode & needed) != needed:
                        dp.chmod(mode | needed)
                        fixed += 1
                except (OSError, PermissionError):
                    pass
            for f in files:
                fp = Path(root) / f
                try:
                    mode = fp.stat().st_mode
                    if (mode & needed) != needed:
                        fp.chmod(mode | needed)
                        fixed += 1
                except (OSError, PermissionError):
                    pass
    except Exception:
        pass
    return fixed


def extract_archive(archive_path: Path, dest_folder: Path) -> Tuple[bool, str]:
    """
    Extract archive using Python libraries.

    Supports:
    - ZIP: zipfile (stdlib)
    - 7z: py7zr
    - RAR: rarfile with bundled UnRAR tool

    Returns (success, error_message).
    """
    ext = archive_path.suffix.lower()
    try:
        if ext == ".zip":
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(dest_folder)
        elif ext == ".7z":
            if not HAS_7Z:
                return False, "py7zr library not available"
            with py7zr.SevenZipFile(archive_path, 'r') as sz:
                sz.extractall(dest_folder)
        elif ext == ".rar":
            if not HAS_RAR_LIB:
                return False, "rarfile library not available"
            with rarfile.RarFile(str(archive_path)) as rf:
                rf.extractall(str(dest_folder))
        else:
            return False, f"Unsupported archive format: {ext}"

        # Fix permissions on extracted content (some archives have read-only folders)
        fix_permissions(dest_folder)
        return True, ""
    except Exception as e:
        return False, str(e)


def get_folder_size(folder_path: Path) -> int:
    """Calculate total size of all files in folder (excluding check.txt)."""
    total = 0
    for f in folder_path.rglob("*"):
        if f.is_file() and f.name != CHECKSUM_FILE:
            try:
                total += f.stat().st_size
            except Exception:
                pass
    return total


def delete_ignored_files(folder_path: Path, ignored_extensions: Set[str]) -> int:
    """
    Delete files with ignored extensions from folder recursively.

    Args:
        folder_path: Path to scan
        ignored_extensions: Set of extensions to delete (e.g., {".mp4", ".avi"})

    Returns count of deleted files.
    """
    deleted = 0
    for f in folder_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in ignored_extensions:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
    return deleted


def delete_video_files(folder_path: Path) -> int:
    """
    Delete video files from folder recursively.

    Convenience wrapper around delete_ignored_files using VIDEO_EXTENSIONS.

    Returns count of deleted files.
    """
    return delete_ignored_files(folder_path, VIDEO_EXTENSIONS)


def scan_extracted_files(folder_path: Path, base_path: Path = None) -> dict[str, int]:
    """
    Scan folder and return dict of {relative_path: size} for all files.

    Args:
        folder_path: Path to scan
        base_path: Base path for relative paths (defaults to folder_path)

    Returns:
        Dict mapping relative file paths to their sizes
    """
    if base_path is None:
        base_path = folder_path

    files = {}
    if not folder_path.exists():
        return files

    for f in folder_path.rglob("*"):
        if f.is_file() and f.name != CHECKSUM_FILE:
            try:
                rel_path = relative_posix(f, base_path)
                files[rel_path] = f.stat().st_size
            except (ValueError, OSError):
                pass

    return files
