"""
Shared utilities for DM Chart Sync.
"""

import os


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
