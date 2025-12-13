"""
Box drawing primitives.

Unicode box-drawing characters and helpers for rendering bordered UI elements.
"""

from ..primitives import Colors

# Box corners
BOX_TL = "╭"  # Top-left
BOX_TR = "╮"  # Top-right
BOX_BL = "╰"  # Bottom-left
BOX_BR = "╯"  # Bottom-right

# Box edges
BOX_H = "─"   # Horizontal
BOX_V = "│"   # Vertical

# Box dividers (for internal horizontal lines)
BOX_TL_DIV = "├"  # Left T-junction
BOX_TR_DIV = "┤"  # Right T-junction


def box_row(left: str, fill: str, right: str, width: int, color: str) -> str:
    """
    Create a box row with colored borders.

    Args:
        left: Left border character
        fill: Fill character (repeated)
        right: Right border character
        width: Total width including borders
        color: ANSI color code for borders

    Returns:
        Formatted string for the row
    """
    return f"{color}{left}{fill * (width - 2)}{right}{Colors.RESET}"
