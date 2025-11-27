"""
Menu system for DM Chart Sync.

Provides interactive terminal menus with in-place rendering.
"""

import sys
import shutil
from dataclasses import dataclass, field
from typing import Any

from .keyboard import getch, KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC


# ============================================================================
# Color System - Gemini-style purple/blue/red gradient
# ============================================================================

# Gradient colors (purple -> blue -> red/pink)
GRADIENT_COLORS = [
    (138, 43, 226),   # Blue-violet
    (123, 44, 191),   # Purple
    (108, 45, 156),   # Deep purple
    (93, 63, 211),    # Slate blue
    (79, 70, 229),    # Indigo
    (99, 102, 241),   # Light indigo
    (129, 140, 248),  # Periwinkle
    (167, 139, 250),  # Light purple
    (196, 118, 232),  # Orchid
    (232, 121, 197),  # Pink
    (244, 114, 182),  # Hot pink
    (251, 113, 133),  # Rose
]

# UI Colors
class Colors:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"

    # Gemini palette
    PURPLE = "\x1b[38;2;138;43;226m"
    BLUE = "\x1b[38;2;79;70;229m"
    PINK = "\x1b[38;2;244;114;182m"
    ROSE = "\x1b[38;2;251;113;133m"
    INDIGO = "\x1b[38;2;99;102;241m"
    VIOLET = "\x1b[38;2;167;139;250m"

    # Functional colors
    SELECTED_BG = "\x1b[48;2;79;70;229m"  # Indigo background
    SELECTED_FG = "\x1b[38;2;255;255;255m"  # White text
    HOTKEY = "\x1b[38;2;167;139;250m"  # Violet for hotkeys
    MUTED = "\x1b[38;2;148;163;184m"  # Slate gray for hints


def rgb(r: int, g: int, b: int) -> str:
    """Generate ANSI escape code for RGB foreground color."""
    return f"\x1b[38;2;{r};{g};{b}m"


def rgb_bg(r: int, g: int, b: int) -> str:
    """Generate ANSI escape code for RGB background color."""
    return f"\x1b[48;2;{r};{g};{b}m"


def lerp_color(color1: tuple, color2: tuple, t: float) -> tuple:
    """Linearly interpolate between two RGB colors."""
    r = int(color1[0] + (color2[0] - color1[0]) * t)
    g = int(color1[1] + (color2[1] - color1[1]) * t)
    b = int(color1[2] + (color2[2] - color1[2]) * t)
    return (r, g, b)


def get_gradient_color(position: float) -> tuple:
    """Get color from gradient at position (0.0 to 1.0)."""
    position = max(0.0, min(1.0, position))

    if position >= 1.0:
        return GRADIENT_COLORS[-1]

    scaled = position * (len(GRADIENT_COLORS) - 1)
    idx = int(scaled)
    t = scaled - idx

    if idx >= len(GRADIENT_COLORS) - 1:
        return GRADIENT_COLORS[-1]

    return lerp_color(GRADIENT_COLORS[idx], GRADIENT_COLORS[idx + 1], t)


def gradient_text(text: str, offset: float = 0.0) -> str:
    """Apply smooth gradient coloring to text with optional offset."""
    if not text:
        return text

    result = []
    text_len = len(text.replace(' ', ''))  # Count non-space chars
    if text_len == 0:
        return text

    char_idx = 0
    for char in text:
        if char == ' ':
            result.append(char)
        else:
            # Position in gradient (0.0 to 1.0)
            pos = (char_idx / text_len) + offset
            pos = pos % 1.0  # Wrap around
            r, g, b = get_gradient_color(pos)
            result.append(f"{rgb(r, g, b)}{char}")
            char_idx += 1

    result.append(Colors.RESET)
    return ''.join(result)


def diagonal_gradient_text(text: str, row: int, total_rows: int, col_weight: float = 0.7) -> str:
    """
    Apply diagonal gradient to text based on row position.

    The gradient flows diagonally from top-left to bottom-right.
    col_weight controls how much horizontal position affects the gradient (0-1).
    """
    if not text:
        return text

    result = []
    text_len = len(text)
    if text_len == 0:
        return text

    # Row contribution to gradient position
    row_offset = (row / max(total_rows - 1, 1)) * (1 - col_weight)

    for col, char in enumerate(text):
        if char == ' ':
            result.append(char)
        else:
            # Combine row and column position for diagonal effect
            col_pos = (col / text_len) * col_weight
            pos = row_offset + col_pos
            pos = min(pos, 1.0)
            r, g, b = get_gradient_color(pos)
            result.append(f"{rgb(r, g, b)}{char}")

    result.append(Colors.RESET)
    return ''.join(result)


# ============================================================================
# ASCII Art Header
# ============================================================================

ASCII_HEADER = r"""
 ██████╗ ███╗   ███╗    ███████╗██╗   ██╗███╗   ██╗ ██████╗
 ██╔══██╗████╗ ████║    ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝
 ██║  ██║██╔████╔██║    ███████╗ ╚████╔╝ ██╔██╗ ██║██║
 ██║  ██║██║╚██╔╝██║    ╚════██║  ╚██╔╝  ██║╚██╗██║██║
 ██████╔╝██║ ╚═╝ ██║    ███████║   ██║   ██║ ╚████║╚██████╗
 ╚═════╝ ╚═╝     ╚═╝    ╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝
""".strip('\n')


def render_header() -> list[str]:
    """Render the ASCII header with smooth diagonal gradient."""
    lines = ASCII_HEADER.split('\n')
    result = []
    for i, line in enumerate(lines):
        # Diagonal gradient: flows from purple (top-left) to pink (bottom-right)
        result.append(diagonal_gradient_text(line, i, len(lines), col_weight=0.6))
    return result


# ============================================================================
# Box Drawing - Rounded style
# ============================================================================

class Box:
    """Rounded box drawing characters."""
    TOP_LEFT = "╭"
    TOP_RIGHT = "╮"
    BOTTOM_LEFT = "╰"
    BOTTOM_RIGHT = "╯"
    HORIZONTAL = "─"
    VERTICAL = "│"
    T_LEFT = "├"
    T_RIGHT = "┤"


def box_top(width: int, color: str = "") -> str:
    """Draw top of box."""
    inner = Box.HORIZONTAL * (width - 2)
    return f"{color}{Box.TOP_LEFT}{inner}{Box.TOP_RIGHT}{Colors.RESET}"


def box_bottom(width: int, color: str = "") -> str:
    """Draw bottom of box."""
    inner = Box.HORIZONTAL * (width - 2)
    return f"{color}{Box.BOTTOM_LEFT}{inner}{Box.BOTTOM_RIGHT}{Colors.RESET}"


def box_line(content: str, width: int, color: str = "", align: str = "left") -> str:
    """Draw a line inside a box."""
    # Strip ANSI codes to get actual content length
    import re
    visible_len = len(re.sub(r'\x1b\[[0-9;]*m', '', content))
    padding_needed = width - 4 - visible_len  # 4 = 2 borders + 2 spaces

    if align == "center":
        left_pad = padding_needed // 2
        right_pad = padding_needed - left_pad
        padded = " " * left_pad + content + " " * right_pad
    else:
        padded = content + " " * padding_needed

    return f"{color}{Box.VERTICAL}{Colors.RESET} {padded} {color}{Box.VERTICAL}{Colors.RESET}"


def box_divider(width: int, color: str = "") -> str:
    """Draw a divider line inside a box."""
    inner = Box.HORIZONTAL * (width - 2)
    return f"{color}{Box.T_LEFT}{inner}{Box.T_RIGHT}{Colors.RESET}"


# ============================================================================
# Menu Components
# ============================================================================

@dataclass
class MenuItem:
    """A selectable menu item."""
    label: str
    hotkey: str | None = None
    value: Any = None
    description: str | None = None

    def __post_init__(self):
        if self.value is None:
            self.value = self.label


@dataclass
class MenuDivider:
    """A visual separator in the menu."""
    pass


@dataclass
class MenuAction:
    """An action item (alias for MenuItem for semantic clarity)."""
    label: str
    hotkey: str | None = None
    value: Any = None
    description: str | None = None

    def __post_init__(self):
        if self.value is None:
            self.value = self.label


@dataclass
class Menu:
    """
    Interactive terminal menu with in-place rendering.

    Uses ANSI escape codes to render the menu and update it in place
    when the user navigates with arrow keys.
    """
    title: str = ""
    footer: str = ""
    items: list = field(default_factory=list)
    show_header: bool = True
    _selected_index: int = 0
    _last_render_height: int = 0
    _box_width: int = 60

    def add_item(self, item: MenuItem | MenuDivider | MenuAction):
        """Add an item to the menu."""
        self.items.append(item)

    def _get_selectable_indices(self) -> list[int]:
        """Get indices of selectable items (not dividers)."""
        return [
            i for i, item in enumerate(self.items)
            if isinstance(item, (MenuItem, MenuAction))
        ]

    def _move_cursor_up(self, lines: int):
        """Move cursor up N lines."""
        if lines > 0:
            sys.stdout.write(f"\x1b[{lines}A")

    def _clear_line(self):
        """Clear the current line."""
        sys.stdout.write("\x1b[2K")

    def _move_to_column(self, col: int = 0):
        """Move cursor to specified column (0 = start)."""
        sys.stdout.write(f"\x1b[{col}G")

    def _calculate_box_width(self) -> int:
        """Calculate the box width based on content."""
        import re
        max_width = 40  # Minimum width

        # Check title
        if self.title:
            max_width = max(max_width, len(self.title) + 8)

        # Check items
        for item in self.items:
            if isinstance(item, (MenuItem, MenuAction)):
                # Calculate visible length
                label = item.label
                if item.description:
                    label += f" ({item.description})"
                hotkey_part = f"[{item.hotkey}] " if item.hotkey else "    "
                line_len = len(hotkey_part) + len(label) + 6  # cursor + padding
                max_width = max(max_width, line_len)

        # Cap at terminal width
        term_width = shutil.get_terminal_size().columns
        return min(max_width + 4, term_width - 2)

    def _render(self, first_render: bool = False):
        """
        Render the menu with styled box and colors.

        On first render, just prints. On subsequent renders, moves cursor
        up to overwrite the previous render.
        """
        import re

        # Move cursor up to overwrite previous render
        if not first_render and self._last_render_height > 0:
            self._move_cursor_up(self._last_render_height)

        lines = []
        box_width = self._calculate_box_width()
        border_color = Colors.INDIGO

        # ASCII Header (only on first render of main menu)
        if self.show_header and first_render:
            lines.extend(render_header())
            lines.append("")

        # Box top
        lines.append(box_top(box_width, border_color))

        # Title
        if self.title:
            title_colored = f"{Colors.BOLD}{gradient_text(self.title)}"
            lines.append(box_line(title_colored, box_width, border_color, align="center"))
            lines.append(box_divider(box_width, border_color))

        # Items
        selectable = self._get_selectable_indices()
        for i, item in enumerate(self.items):
            if isinstance(item, MenuDivider):
                lines.append(box_divider(box_width, border_color))
            elif isinstance(item, (MenuItem, MenuAction)):
                is_selected = (i == self._selected_index)

                # Build the content
                if item.hotkey:
                    hotkey_str = f"{Colors.HOTKEY}[{item.hotkey}]{Colors.RESET} "
                else:
                    hotkey_str = "    "

                label = item.label
                if item.description:
                    label += f" {Colors.MUTED}({item.description}){Colors.RESET}"

                if is_selected:
                    # Highlighted selection with arrow
                    cursor = f"{Colors.PINK}▸{Colors.RESET} "
                    content = f"{cursor}{hotkey_str}{Colors.BOLD}{label}{Colors.RESET}"
                else:
                    cursor = "  "
                    content = f"{cursor}{hotkey_str}{label}"

                lines.append(box_line(content, box_width, border_color))

        # Footer
        if self.footer:
            lines.append(box_divider(box_width, border_color))
            footer_colored = f"{Colors.MUTED}{self.footer}{Colors.RESET}"
            lines.append(box_line(footer_colored, box_width, border_color, align="center"))

        # Box bottom
        lines.append(box_bottom(box_width, border_color))

        # Navigation hint
        hint = f"{Colors.MUTED}↑/↓ Navigate  {Colors.HOTKEY}Enter{Colors.MUTED} Select  {Colors.HOTKEY}Esc{Colors.MUTED} Cancel{Colors.RESET}"
        lines.append(f"  {hint}")

        # Render all lines
        for line in lines:
            self._clear_line()
            self._move_to_column(0)
            sys.stdout.write(line + "\n")

        sys.stdout.flush()
        self._last_render_height = len(lines)

    def run(self) -> MenuItem | MenuAction | None:
        """
        Run the menu and return the selected item.

        Returns None if the user cancels (ESC).
        """
        selectable = self._get_selectable_indices()
        if not selectable:
            return None

        # Start at first selectable item
        self._selected_index = selectable[0]

        # Build hotkey map
        hotkeys = {}
        for i, item in enumerate(self.items):
            if isinstance(item, (MenuItem, MenuAction)) and item.hotkey:
                hotkeys[item.hotkey.upper()] = i

        # Initial render
        self._render(first_render=True)

        while True:
            key = getch(return_special_keys=True)

            if key == KEY_ESC:
                return None

            elif key == KEY_UP:
                # Move to previous selectable item
                current_pos = selectable.index(self._selected_index)
                if current_pos > 0:
                    self._selected_index = selectable[current_pos - 1]
                    self._render()

            elif key == KEY_DOWN:
                # Move to next selectable item
                current_pos = selectable.index(self._selected_index)
                if current_pos < len(selectable) - 1:
                    self._selected_index = selectable[current_pos + 1]
                    self._render()

            elif key == KEY_ENTER:
                return self.items[self._selected_index]

            elif isinstance(key, str) and len(key) == 1:
                # Check for hotkey
                upper_key = key.upper()
                if upper_key in hotkeys:
                    self._selected_index = hotkeys[upper_key]
                    return self.items[self._selected_index]

                # Check for number keys (1-9)
                if key.isdigit() and key != '0':
                    idx = int(key)
                    # Find the Nth selectable item
                    if idx <= len(selectable):
                        self._selected_index = selectable[idx - 1]
                        return self.items[self._selected_index]
