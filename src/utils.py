"""
Shared utilities for DM Chart Sync.
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional


class TeeOutput:
    """Write to both stdout and a log file, filtering out UI noise."""

    # Patterns to skip in log file (menus, ASCII art, etc.)
    _SKIP_PATTERNS = [
        r'[╭│╰├╮╯┤─┬┴╔╗╚╝═║]',  # Box drawing characters (menus)
        r'[█▀▄░▒▓]',             # Block characters (ASCII art banner)
        r'[▸▼▲►◀]',              # Menu cursor/expand indicators
        r'↑.*↓.*Navigate',       # Menu navigation instructions
        r'^\s*$',                 # Blank lines
        r'by Dichotic',          # Version tagline (part of banner)
        r'^\s*↓.*MB\s*\(\d+%\)', # Download progress lines (↓ File: X/Y MB (N%))
    ]

    def __init__(self, log_path: Path):
        self.terminal = sys.stdout
        self.log_file = open(log_path, "a", encoding="utf-8")
        self._skip_regex = re.compile('|'.join(self._SKIP_PATTERNS))
        self._line_buffer = ""
        # Write session header
        self.log_file.write(f"\n{'='*60}\n")
        self.log_file.write(f"Session started: {datetime.now().isoformat()}\n")
        self.log_file.write(f"{'='*60}\n\n")
        self.log_file.flush()

    def write(self, message):
        self.terminal.write(message)

        # Strip ANSI escape codes
        clean = re.sub(r'\x1b\[[0-9;]*[mKHJ]', '', message)

        # Buffer partial lines (for \r carriage return handling)
        self._line_buffer += clean

        # Process complete lines
        while '\n' in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split('\n', 1)
            # Skip UI noise
            if not self._skip_regex.search(line):
                # Skip empty lines and lines that are just carriage return overwrites
                stripped = line.rstrip()
                if stripped and not stripped.startswith('\r'):
                    timestamp = datetime.now().strftime("[%H:%M:%S]")
                    self.log_file.write(f"{timestamp} {stripped}\n")

        # Handle \r (carriage return) - only keep the last version
        if '\r' in self._line_buffer:
            self._line_buffer = self._line_buffer.rsplit('\r', 1)[-1]

        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        # Flush any remaining buffer
        if self._line_buffer.strip() and not self._skip_regex.search(self._line_buffer):
            timestamp = datetime.now().strftime("[%H:%M:%S]")
            self.log_file.write(f"{timestamp} {self._line_buffer.rstrip()}\n")
        self.log_file.close()


# ============================================================================
# Google Drive URL parsing
# ============================================================================

def parse_drive_folder_url(url_or_id: str) -> tuple[str | None, str | None]:
    """
    Extract Google Drive folder ID from a URL or raw ID.

    Supports formats:
    - https://drive.google.com/drive/folders/FOLDER_ID
    - https://drive.google.com/drive/folders/FOLDER_ID?usp=sharing
    - https://drive.google.com/drive/u/0/folders/FOLDER_ID
    - Raw folder ID (alphanumeric with - and _)

    Args:
        url_or_id: URL or folder ID string

    Returns:
        Tuple of (folder_id, error_message)
        - (folder_id, None) if valid
        - (None, error_message) if invalid
    """
    url_or_id = url_or_id.strip()

    # Check if it's a Google Drive file link (not a folder)
    file_pattern = r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"
    if re.search(file_pattern, url_or_id):
        return None, "That's a file link, not a folder link"

    # Pattern for folder ID in URL path
    folder_pattern = r"drive\.google\.com/drive(?:/u/\d+)?/folders/([a-zA-Z0-9_-]+)"
    match = re.search(folder_pattern, url_or_id)
    if match:
        return match.group(1), None

    # Check if it's a raw folder ID (alphanumeric with - and _, typically 10+ chars)
    raw_id_pattern = r"^[a-zA-Z0-9_-]{10,}$"
    if re.match(raw_id_pattern, url_or_id):
        return url_or_id, None

    # Check if it looks like a Google Drive URL but wrong format
    if "drive.google.com" in url_or_id:
        return None, "Unrecognized Google Drive URL format"

    return None, "Not a Google Drive URL"


# ============================================================================
# Filename sanitization (cross-platform)
# ============================================================================

# Illegal characters mapped to safe alternatives
# Using simple ASCII replacements instead of fullwidth Unicode (cleaner filenames)
ILLEGAL_CHAR_MAP = {
    "<": "-",    # Less-than
    ">": "-",    # Greater-than
    ":": " -",   # Colon -> space-dash (e.g., "Guitar Hero: Aerosmith" -> "Guitar Hero - Aerosmith")
    '"': "'",    # Double quote -> single quote
    "\\": "-",   # Backslash
    "/": "-",    # Forward slash
    "|": "-",    # Pipe
    "?": "",     # Question mark -> remove
    "*": "",     # Asterisk -> remove
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


def set_terminal_size(cols: int = 90, rows: int = 40):
    """
    Set terminal window size.

    Args:
        cols: Number of columns (width)
        rows: Number of rows (height)
    """
    if os.name == 'nt':
        # Windows: use mode command
        os.system(f'mode con: cols={cols} lines={rows}')
    else:
        # macOS/Linux: use ANSI escape sequence
        # \x1b[8;{rows};{cols}t sets window size
        print(f'\x1b[8;{rows};{cols}t', end='', flush=True)


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


def print_long_path_warning(count: int):
    """Print Windows long path warning with registry fix instructions."""
    print(f"  WARNING: {count} files skipped due to path length > 260 chars")
    print(f"  To fix: Enable long paths in Windows Registry:")
    print(f"    HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control\\FileSystem")
    print(f"    Set LongPathsEnabled to 1, then restart")


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
