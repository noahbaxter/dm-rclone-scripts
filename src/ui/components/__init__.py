"""
Reusable visual building blocks.

Non-interactive components for rendering UI elements.
"""

from .box import (
    BOX_TL,
    BOX_TR,
    BOX_BL,
    BOX_BR,
    BOX_H,
    BOX_V,
    BOX_TL_DIV,
    BOX_TR_DIV,
    box_row,
)
from .header import (
    ASCII_HEADER,
    print_header,
)
from .formatting import (
    strip_ansi,
    format_colored_count,
    format_colored_size,
    format_sync_subtitle,
    format_purge_tree,
)

__all__ = [
    # Box drawing
    "BOX_TL",
    "BOX_TR",
    "BOX_BL",
    "BOX_BR",
    "BOX_H",
    "BOX_V",
    "BOX_TL_DIV",
    "BOX_TR_DIV",
    "box_row",
    # Header
    "ASCII_HEADER",
    "print_header",
    # Formatting
    "strip_ansi",
    "format_colored_count",
    "format_colored_size",
    "format_sync_subtitle",
    "format_purge_tree",
]
