"""
Shared utilities for DM Chart Sync.
"""

import os
from typing import Any, Callable, List, Optional


# ============================================================================
# Filename sanitization (cross-platform)
# ============================================================================

# Illegal characters mapped to visually-similar fullwidth Unicode equivalents
ILLEGAL_CHAR_MAP = {
    "<": "＜",   # U+FF1C FULLWIDTH LESS-THAN SIGN
    ">": "＞",   # U+FF1E FULLWIDTH GREATER-THAN SIGN
    ":": "：",   # U+FF1A FULLWIDTH COLON
    '"': "＂",   # U+FF02 FULLWIDTH QUOTATION MARK
    "\\": "＼",  # U+FF3C FULLWIDTH REVERSE SOLIDUS
    "/": "／",   # U+FF0F FULLWIDTH SOLIDUS
    "|": "｜",   # U+FF5C FULLWIDTH VERTICAL LINE
    "?": "？",   # U+FF1F FULLWIDTH QUESTION MARK
    "*": "＊",   # U+FF0A FULLWIDTH ASTERISK
}

# Control characters (0x00-0x1F) and DEL (0x7F) - no visual equivalent, use _
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
    - Illegal characters: < > : " \\ / | ? * → fullwidth Unicode equivalents
    - Control characters (0x00-0x1F) and DEL (0x7F) → _
    - Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) → prefixed with _
    - Trailing dots and spaces (Windows strips these silently) → stripped

    Args:
        filename: Original filename (not a full path)

    Returns:
        Sanitized filename safe for Windows, macOS, and Linux
    """
    if not filename:
        return filename

    # Replace illegal chars with fullwidth equivalents, control chars with _
    result = []
    for char in filename:
        if char in ILLEGAL_CHAR_MAP:
            result.append(ILLEGAL_CHAR_MAP[char])
        elif char in CONTROL_CHARS:
            result.append("_")
        else:
            result.append(char)
    filename = "".join(result)

    # Strip trailing dots and spaces (Windows silently removes these)
    filename = filename.rstrip(". ")

    # Handle Windows reserved names (e.g., CON, PRN, NUL)
    # Check the base name without extension
    name_upper = filename.upper()
    base_name = name_upper.split(".")[0] if "." in name_upper else name_upper
    if base_name in WINDOWS_RESERVED_NAMES:
        filename = "_" + filename

    # If filename became empty, use placeholder
    if not filename:
        filename = "_"

    return filename


def sanitize_path(path: str) -> str:
    """
    Sanitize each component of a path for cross-platform compatibility.

    Args:
        path: Path string (e.g., "folder/subfolder/file.txt")

    Returns:
        Path with each component sanitized
    """
    # Normalize to forward slashes
    path = path.replace("\\", "/")

    # Sanitize each component
    parts = path.split("/")
    sanitized_parts = [sanitize_filename(part) for part in parts]

    return "/".join(sanitized_parts)


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

    Returns:
        Sorted list
    """
    if key is None:
        return sorted(items, key=name_sort_key)
    return sorted(items, key=lambda x: name_sort_key(key(x)))


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


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


def get_terminal_width() -> int:
    """Get terminal width, with fallback."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def print_progress(message: str, prefix: str = "  "):
    """
    Print a progress message that overwrites the previous line.

    Handles narrow terminals by truncating and using ANSI clear codes.
    """
    width = get_terminal_width()
    full_msg = f"{prefix}{message}"

    # Truncate if too long (leave room for cursor)
    if len(full_msg) >= width:
        full_msg = full_msg[:width - 4] + "..."

    # Clear line and print (\033[2K clears entire line)
    print(f"\033[2K\r{full_msg}", end="", flush=True)
