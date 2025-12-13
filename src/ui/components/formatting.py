"""
Text formatting helpers for UI display.

Functions for formatting sync status, counts, sizes with colors.
"""

import math
import re
from collections import defaultdict
from pathlib import Path

from src.core.formatting import format_size
from ..primitives import Colors


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def calc_percent(synced: int, total: int) -> int:
    """Calculate sync percentage, always rounding down."""
    if total == 0:
        return 100
    return math.floor(synced / total * 100)


def format_delta(
    add_size: int = 0,
    add_files: int = 0,
    add_charts: int = 0,
    remove_size: int = 0,
    remove_files: int = 0,
    remove_charts: int = 0,
    mode: str = "size",
    empty_text: str = "",
) -> str:
    """
    Format add/remove delta with combined brackets.

    Modes:
        "size": [+2.3 GB / -317.3 MB]
        "files": [+50 files / -80 files]
        "charts": [+50 charts / -80 charts]

    Bracket colors:
        Add only: white [...]
        Remove only: red [...]
        Both: white [ + white add + / + red remove + red ]
    """
    if mode == "size":
        has_add = add_size > 0
        has_remove = remove_size > 0
        add_str = f"+{format_size(add_size)}" if has_add else ""
        remove_str = f"-{format_size(remove_size)}" if has_remove else ""
    elif mode == "charts":
        has_add = add_charts > 0
        has_remove = remove_charts > 0
        unit = "chart" if add_charts == 1 else "charts"
        add_str = f"+{add_charts} {unit}" if has_add else ""
        unit = "chart" if remove_charts == 1 else "charts"
        remove_str = f"-{remove_charts} {unit}" if has_remove else ""
    else:  # files
        has_add = add_files > 0
        has_remove = remove_files > 0
        unit = "file" if add_files == 1 else "files"
        add_str = f"+{add_files} {unit}" if has_add else ""
        unit = "file" if remove_files == 1 else "files"
        remove_str = f"-{remove_files} {unit}" if has_remove else ""

    if has_add and has_remove:
        # White [ and add, muted /, red remove and ]
        return f"{Colors.RESET}{Colors.BOLD}[{add_str} {Colors.MUTED}/{Colors.RESET} {Colors.RED}{remove_str}]{Colors.RESET}"
    elif has_add:
        # All white
        return f"{Colors.RESET}{Colors.BOLD}[{add_str}]{Colors.RESET}"
    elif has_remove:
        # All red
        return f"{Colors.RED}[{remove_str}]{Colors.RESET}"
    else:
        return empty_text


def format_status_line(
    synced_charts: int,
    total_charts: int,
    enabled_setlists: int,
    total_setlists: int,
    total_size: int,
    synced_size: int = 0,
    missing_charts: int = 0,
    purgeable_files: int = 0,
    purgeable_charts: int = 0,
    purgeable_size: int = 0,
    delta_mode: str = "size",
) -> str:
    """
    Format status line: 100% | 562/562 charts, 10/15 setlists (4.0 GB)

    With delta: 100% | 562/562 charts, 10/15 setlists (4.0 GB) [+50 charts / -80 charts]
    """
    if total_charts == 0 and purgeable_files == 0 and missing_charts == 0:
        return ""

    pct = calc_percent(synced_charts, total_charts)

    parts = []
    if total_charts > 0:
        parts.append(f"{synced_charts}/{total_charts} charts")
    if total_setlists > 0:
        parts.append(f"{enabled_setlists}/{total_setlists} setlists")

    info = ", ".join(parts)
    if total_size > 0:
        info += f" ({format_size(total_size)})"

    result = f"{pct}% | {info}"

    # Show full delta (add + remove)
    missing_size = max(0, total_size - synced_size) if synced_size > 0 else 0
    has_delta = missing_charts > 0 or purgeable_files > 0 or purgeable_charts > 0 or missing_size > 0
    if has_delta:
        delta = format_delta(
            add_size=missing_size,
            add_files=missing_charts,
            add_charts=missing_charts,
            remove_size=purgeable_size,
            remove_files=purgeable_files,
            remove_charts=purgeable_charts,
            mode=delta_mode,
        )
        if delta:
            result += f" {delta}"

    return result


def format_home_item(
    enabled_setlists: int,
    total_setlists: int,
    total_size: int,
    synced_size: int,
    purgeable_files: int = 0,
    purgeable_charts: int = 0,
    purgeable_size: int = 0,
    missing_charts: int = 0,
    disabled: bool = False,
    delta_mode: str = "size",
) -> str:
    """
    Format home screen item line.

    Enabled synced: 100% | 5/30 setlists, 4.0 GB
    Enabled partial: 35% | 5/30 setlists, [+2.3 GB] or [+50 files]
    Disabled: 5/30 setlists, 4.0 GB (greyed by caller)
    With purgeable: ... [+2.3 GB / -317 MB] or [+50 files / -80 files]
    """
    # Setlists part
    if total_setlists > 0:
        setlists_str = f"{enabled_setlists}/{total_setlists} setlists"
    else:
        setlists_str = ""

    missing_size = max(0, total_size - synced_size)

    if disabled:
        # Disabled: no percentage, show totals greyed (caller handles grey)
        parts = []
        if setlists_str:
            parts.append(setlists_str)
        if total_size > 0:
            parts.append(format_size(total_size))
        result = ", ".join(parts) if parts else ""
        # Disabled items only show purgeable (no add delta)
        if purgeable_files > 0 or purgeable_charts > 0 or purgeable_size > 0:
            delta = format_delta(
                remove_size=purgeable_size,
                remove_files=purgeable_files,
                remove_charts=purgeable_charts,
                mode=delta_mode,
            )
            if delta:
                result = f"{result} {delta}" if result else delta
    else:
        # Enabled: show percentage and size/delta
        is_synced = missing_size <= 0
        pct = 100 if is_synced else calc_percent(synced_size, total_size)

        parts = []
        if setlists_str:
            parts.append(setlists_str)

        if is_synced:
            if total_size > 0:
                parts.append(format_size(total_size))
            info = ", ".join(parts) if parts else ""
            result = f"{pct}% | {info}" if info else f"{pct}%"
            # Synced but has purgeable
            if purgeable_files > 0 or purgeable_charts > 0 or purgeable_size > 0:
                delta = format_delta(
                    remove_size=purgeable_size,
                    remove_files=purgeable_files,
                    remove_charts=purgeable_charts,
                    mode=delta_mode,
                )
                if delta:
                    result += f" {delta}"
        else:
            info = ", ".join(parts) if parts else ""
            # Has missing - combine add and remove in one delta
            delta = format_delta(
                add_size=missing_size,
                add_files=missing_charts,  # Use chart count for files (best we have)
                add_charts=missing_charts,
                remove_size=purgeable_size,
                remove_files=purgeable_files,
                remove_charts=purgeable_charts,
                mode=delta_mode,
            )
            if delta:
                if info:
                    result = f"{pct}% | {info} {delta}"
                else:
                    result = f"{pct}% | {delta}"
            else:
                result = f"{pct}% | {info}" if info else f"{pct}%"

    return result


def format_setlist_item(
    total_charts: int,
    synced_charts: int,
    total_size: int,
    synced_size: int,
    purgeable_files: int = 0,
    purgeable_charts: int = 0,
    purgeable_size: int = 0,
    missing_charts: int = 0,
    disabled: bool = False,
    unit: str = "charts",
    delta_mode: str = "size",
) -> str:
    """
    Format setlist item line.

    Enabled synced: 100% | 427 charts, 3.8 GB
    Enabled partial: 80% | 427 charts, [+500 MB] or [+50 files]
    Disabled: 427 charts, 3.8 GB (greyed by caller)
    With purgeable: ... [+500 MB / -200 MB] or [+50 files / -200 files]
    """
    # Charts/archives count
    count_str = f"{total_charts} {unit}" if total_charts > 0 else ""
    missing_size = max(0, total_size - synced_size)

    if disabled:
        # Disabled: no percentage, show totals (caller handles grey)
        parts = []
        if count_str:
            parts.append(count_str)
        if total_size > 0:
            parts.append(format_size(total_size))
        result = ", ".join(parts) if parts else ""
        # Disabled items only show purgeable (no add delta)
        if purgeable_files > 0 or purgeable_charts > 0 or purgeable_size > 0:
            delta = format_delta(
                remove_size=purgeable_size,
                remove_files=purgeable_files,
                remove_charts=purgeable_charts,
                mode=delta_mode,
            )
            if delta:
                result = f"{result} {delta}" if result else delta
    else:
        # Enabled: show percentage and size/delta
        is_synced = synced_charts >= total_charts or missing_size <= 0
        pct = calc_percent(synced_charts, total_charts) if total_charts > 0 else 100

        parts = []
        if count_str:
            parts.append(count_str)

        if is_synced:
            if total_size > 0:
                parts.append(format_size(total_size))
            info = ", ".join(parts) if parts else ""
            result = f"{pct}% | {info}" if info else f"{pct}%"
            # Synced but has purgeable
            if purgeable_files > 0 or purgeable_charts > 0 or purgeable_size > 0:
                delta = format_delta(
                    remove_size=purgeable_size,
                    remove_files=purgeable_files,
                    remove_charts=purgeable_charts,
                    mode=delta_mode,
                )
                if delta:
                    result += f" {delta}"
        else:
            info = ", ".join(parts) if parts else ""
            # Has missing - combine add and remove in one delta
            delta = format_delta(
                add_size=missing_size,
                add_files=missing_charts,  # Use chart count for files (best we have)
                add_charts=missing_charts,
                remove_size=purgeable_size,
                remove_files=purgeable_files,
                remove_charts=purgeable_charts,
                mode=delta_mode,
            )
            if delta:
                if info:
                    result = f"{pct}% | {info} {delta}"
                else:
                    result = f"{pct}% | {delta}"
            else:
                result = f"{pct}% | {info}" if info else f"{pct}%"

    return result


def format_drive_status(
    synced_charts: int,
    total_charts: int,
    enabled_setlists: int,
    total_setlists: int,
    total_size: int,
    synced_size: int = 0,
    missing_charts: int = 0,
    purgeable_files: int = 0,
    purgeable_charts: int = 0,
    purgeable_size: int = 0,
    disabled: bool = False,
    delta_mode: str = "size",
) -> str:
    """
    Format drive config status line.

    Enabled: 100% | 562/562 charts, 5/30 setlists (4.0 GB) [+50 charts / -80 charts]
    Disabled: DISABLED [-317 MB]
    """
    if disabled:
        if purgeable_files > 0 or purgeable_charts > 0:
            delta = format_delta(
                remove_size=purgeable_size,
                remove_files=purgeable_files,
                remove_charts=purgeable_charts,
                mode=delta_mode,
            )
            return f"{Colors.MUTED}DISABLED{Colors.RESET} {delta}"
        return f"{Colors.MUTED}DISABLED{Colors.RESET}"

    return format_status_line(
        synced_charts=synced_charts,
        total_charts=total_charts,
        enabled_setlists=enabled_setlists,
        total_setlists=total_setlists,
        total_size=total_size,
        synced_size=synced_size,
        missing_charts=missing_charts,
        purgeable_files=purgeable_files,
        purgeable_charts=purgeable_charts,
        purgeable_size=purgeable_size,
        delta_mode=delta_mode,
    )


def format_purge_tree(files: list[tuple[Path, int]], base_path: Path) -> list[str]:
    """
    Format files to purge as a tree showing file counts per folder.

    Args:
        files: List of (Path, size) tuples
        base_path: Base path for relative display

    Returns:
        List of formatted strings to print.
    """
    by_folder = defaultdict(lambda: {"count": 0, "size": 0})
    for f, size in files:
        rel_path = f.relative_to(base_path)
        parent = str(rel_path.parent)
        by_folder[parent]["count"] += 1
        by_folder[parent]["size"] += size

    sorted_folders = sorted(by_folder.items())

    lines = []
    for folder_path, stats in sorted_folders:
        file_word = "file" if stats["count"] == 1 else "files"
        lines.append(f"  {folder_path}/ ({stats['count']} {file_word}, {format_size(stats['size'])})")

    return lines
