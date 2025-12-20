"""
Formatting and sanitization utilities for DM Chart Sync.
"""

import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, List, Optional, Union


# ============================================================================
# Filename sanitization (cross-platform)
# ============================================================================

# Illegal characters mapped to safe alternatives
ILLEGAL_CHAR_MAP = {
    "<": "-",
    ">": "-",
    ":": " -",   # Colon -> space-dash (e.g., "Title: Subtitle" -> "Title - Subtitle")
    '"': "'",
    "\\": "-",
    "/": "-",
    "|": "-",
    "?": "",
    "*": "",
}

# Control characters (0x00-0x1F) and DEL (0x7F)
CONTROL_CHARS = set(chr(i) for i in range(32)) | {chr(127)}

# Windows reserved device names (case-insensitive)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename for cross-platform compatibility.

    Handles:
    - Illegal characters: < > : " \\ / | ? * → safe equivalents
    - Control characters (0x00-0x1F) and DEL (0x7F) → _
    - Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) → prefixed with _
    - Trailing dots and spaces (Windows strips these silently) → stripped
    """
    if not filename:
        return filename

    # Normalize Unicode to NFC to match scan_local_files behavior.
    # macOS and some sources use NFD (decomposed), Windows expects NFC (composed).
    # Without this, "Pokémon" (NFD) won't match "Pokémon" (NFC) in path comparisons.
    filename = unicodedata.normalize("NFC", filename)

    result = []
    for char in filename:
        if char in ILLEGAL_CHAR_MAP:
            result.append(ILLEGAL_CHAR_MAP[char])
        elif char in CONTROL_CHARS:
            result.append("_")
        else:
            result.append(char)
    filename = "".join(result)

    # Strip trailing dots and spaces
    filename = filename.rstrip(". ")

    # Handle Windows reserved names
    name_upper = filename.upper()
    base_name = name_upper.split(".")[0] if "." in name_upper else name_upper
    if base_name in WINDOWS_RESERVED_NAMES:
        filename = "_" + filename

    if not filename:
        filename = "_"

    return filename


def sanitize_path(path: str) -> str:
    """
    Sanitize each component of a path for cross-platform compatibility.

    Handles escaped slashes: "//" in folder names is treated as a literal slash
    (becomes "-" after sanitization), while single "/" is a path separator.
    """
    path = path.replace("\\", "/")
    # Split only on single "/" - consecutive slashes like "//" are part of folder names
    # e.g., "Setlist/Heart // Mind/song.ini" → ["Setlist", "Heart // Mind", "song.ini"]
    parts = re.split(r"(?<!/)/(?!/)", path)
    sanitized_parts = [sanitize_filename(part) for part in parts]
    return "/".join(sanitized_parts)


# ============================================================================
# Cross-platform path utilities
# ============================================================================

def to_posix(path: Union[str, Path]) -> str:
    """
    Convert a path to a posix-style string (forward slashes).

    Works consistently across platforms - use this instead of str(path)
    when storing or comparing paths.
    """
    if isinstance(path, Path):
        return path.as_posix()
    return path.replace("\\", "/")


def relative_posix(path: Path, base: Path) -> str:
    """
    Get the relative path as a posix-style string.

    Use instead of str(path.relative_to(base)) for cross-platform consistency.
    """
    return path.relative_to(base).as_posix()


def parent_posix(path: Union[str, Path]) -> str:
    """
    Get the parent directory as a posix-style string.

    Use instead of str(Path(path).parent) for cross-platform consistency.
    """
    if isinstance(path, str):
        path = Path(path)
    return path.parent.as_posix()


# ============================================================================
# Size and duration formatting
# ============================================================================

def format_size(size_bytes: int) -> str:
    """Format bytes as human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format seconds as human readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"


# ============================================================================
# Sorting utilities
# ============================================================================

def name_sort_key(name: str) -> str:
    """Sort key for case-insensitive name sorting."""
    return name.casefold()


def sort_by_name(items: List[Any], key: Optional[Callable[[Any], str]] = None) -> List[Any]:
    """
    Sort items by name, case-insensitive.

    Args:
        items: List of items to sort
        key: Optional function to extract name from item (default: item itself)
    """
    if key is None:
        return sorted(items, key=name_sort_key)
    return sorted(items, key=lambda x: name_sort_key(key(x)))


# ============================================================================
# File deduplication
# ============================================================================

def dedupe_files_by_newest(files: list) -> list:
    """
    Deduplicate files with same path, keeping only newest version.

    Some charters upload multiple versions with same filename - we only want the newest.
    Uses sanitized paths as keys so paths differing only by illegal chars (like trailing
    spaces) are treated as duplicates.

    Args:
        files: List of file dicts with "path" and "modified" keys

    Returns:
        Deduplicated list with only newest version of each path
    """
    by_path = {}
    for f in files:
        path = f.get("path", "")
        # Use sanitized path as key - paths that differ only by illegal chars
        # (like trailing spaces) should be treated as duplicates
        key = sanitize_path(path)
        modified = f.get("modified", "")
        if key not in by_path or modified > by_path[key].get("modified", ""):
            by_path[key] = f
    return list(by_path.values())
