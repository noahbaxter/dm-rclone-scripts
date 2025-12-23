"""
Terminal utilities for DM Chart Sync.

Handles terminal size, clearing, and progress display.
"""

import os


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


SECTION_WIDTH = 50


def print_section_header(name: str, width: int = SECTION_WIDTH):
    """Print a styled section header using box-drawing characters."""
    from .colors import Colors
    c = Colors
    header = f"━━━ {name} "
    header += "━" * max(5, width - len(header))
    print(f"\n{c.BOLD}{header}{c.RESET}")


def make_separator(char: str = "━", width: int = SECTION_WIDTH) -> str:
    """Create a horizontal separator line string."""
    return char * width


def print_separator(char: str = "━", width: int = SECTION_WIDTH):
    """Print a horizontal separator line."""
    print(make_separator(char, width))
