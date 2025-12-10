"""
Formatting and sanitization utilities for DM Chart Sync.
"""

from typing import Any, Callable, List, Optional


# ============================================================================
# Filename sanitization (cross-platform)
# ============================================================================

# Illegal characters mapped to safe alternatives
ILLEGAL_CHAR_MAP = {
    "<": "-",
    ">": "-",
    ":": " -",   # Colon -> space-dash (e.g., "Guitar Hero: Aerosmith" -> "Guitar Hero - Aerosmith")
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
    """
    path = path.replace("\\", "/")
    parts = path.split("/")
    sanitized_parts = [sanitize_filename(part) for part in parts]
    return "/".join(sanitized_parts)


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
