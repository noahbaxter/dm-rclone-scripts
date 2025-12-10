"""
Text formatting helpers for UI display.

Functions for formatting sync status, counts, sizes with colors.
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.formatting import format_size
from ..primitives import Colors

if TYPE_CHECKING:
    from src.sync import SyncStatus


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def format_colored_count(
    synced: int,
    total: int,
    excess: int = 0,
    synced_is_excess: bool = False
) -> str:
    """
    Format a colored count display.

    Args:
        synced: Number of synced items
        total: Total number of items
        excess: Number of excess items (shown in red prefix)
        synced_is_excess: If True, show synced in red (for disabled items with content)

    Returns:
        Formatted string like "20 + 108/108" with colors (caller adds unit if needed)
        Or just "45" in red if total is 0 but excess > 0
    """
    m = Colors.MUTED

    if excess > 0:
        if total == 0:
            return f"{Colors.RED}{excess}"
        return f"{Colors.RED}{excess}{m} + {Colors.RESET}{synced}{m}/{total}"
    elif synced_is_excess and synced > 0:
        return f"{Colors.RED}{synced}{m}/{total}"
    elif synced > 0:
        return f"{Colors.RESET}{synced}{m}/{total}"
    else:
        return f"{synced}/{total}"


def format_colored_size(
    synced_size: int,
    total_size: int,
    excess_size: int = 0,
    synced_is_excess: bool = False
) -> str:
    """
    Format a colored size display.

    Args:
        synced_size: Size of synced data
        total_size: Total size
        excess_size: Size of excess data (shown in red prefix)
        synced_is_excess: If True, show synced_size in red (for disabled items with content)

    Returns:
        Formatted string like "1.6 GB + 4.2 GB/4.2 GB" with colors
        Or just "1.5 GB" in red if total_size is 0 but excess_size > 0
    """
    m = Colors.MUTED

    if excess_size > 0:
        if total_size == 0:
            return f"{Colors.RED}{format_size(excess_size)}"
        return f"{Colors.RED}{format_size(excess_size)}{m} + {Colors.RESET}{format_size(synced_size)}{m}/{format_size(total_size)}"
    elif synced_is_excess and synced_size > 0:
        effective_total = total_size if total_size > 0 else synced_size
        return f"{Colors.RED}{format_size(synced_size)}{m}/{format_size(effective_total)}"
    elif synced_size > 0:
        effective_total = total_size if total_size > 0 else synced_size
        return f"{Colors.RESET}{format_size(synced_size)}{m}/{format_size(effective_total)}"
    else:
        return format_size(total_size)


def format_sync_subtitle(
    status: "SyncStatus",
    unit: str = "charts",
    excess_size: int = 0
) -> str:
    """
    Format a sync status subtitle line.

    Args:
        status: SyncStatus with chart/archive counts
        unit: "charts" or "archives"
        excess_size: Size of excess data (purgeable, shown in red)

    Returns:
        Formatted string like "Synced: 108/108 charts (4.2 GB + 1.6 GB/4.2 GB) | 100%"
        Or if everything is purgeable: "Purgeable: 1.5 GB"
    """
    if status.total_charts == 0:
        if excess_size > 0:
            return f"Purgeable: {Colors.RED}{format_size(excess_size)}{Colors.MUTED}"
        return ""

    pct = (status.synced_charts / status.total_charts * 100)
    charts_str = format_colored_count(status.synced_charts, status.total_charts)

    effective_total_size = status.total_size if status.total_size > 0 else status.synced_size
    size_str = format_colored_size(status.synced_size, effective_total_size, excess_size=excess_size)

    return f"Synced: {charts_str} {unit} ({size_str}) | {pct:.0f}%"


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
