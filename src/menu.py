"""
Menu system for DM Chart Sync.

Provides interactive terminal menus with in-place rendering.
"""

import os
import re
import signal
import sys
import shutil
from dataclasses import dataclass, field
from typing import Any

from .keyboard import getch, KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


# Global flag for resize detection
_resize_flag = False


def _handle_resize(signum, frame):
    """Signal handler for terminal resize (SIGWINCH)."""
    global _resize_flag
    _resize_flag = True


# Install signal handler (Unix only)
if hasattr(signal, 'SIGWINCH'):
    signal.signal(signal.SIGWINCH, _handle_resize)


# ============================================================================
# Color System - Gemini-style purple/blue/red gradient
# ============================================================================

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


class Colors:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    PURPLE = "\x1b[38;2;138;43;226m"
    INDIGO = "\x1b[38;2;99;102;241m"
    PINK = "\x1b[38;2;244;114;182m"
    HOTKEY = "\x1b[38;2;167;139;250m"
    MUTED = "\x1b[38;2;148;163;184m"


def rgb(r: int, g: int, b: int) -> str:
    return f"\x1b[38;2;{r};{g};{b}m"


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def get_gradient_color(pos: float) -> tuple:
    """Get interpolated color at position 0.0-1.0."""
    pos = max(0.0, min(1.0, pos))
    scaled = pos * (len(GRADIENT_COLORS) - 1)
    idx = int(scaled)
    if idx >= len(GRADIENT_COLORS) - 1:
        return GRADIENT_COLORS[-1]
    return lerp_color(GRADIENT_COLORS[idx], GRADIENT_COLORS[idx + 1], scaled - idx)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


# ============================================================================
# Header - Standalone component
# ============================================================================

ASCII_HEADER = r"""
 ██████╗ ███╗   ███╗    ███████╗██╗   ██╗███╗   ██╗ ██████╗
 ██╔══██╗████╗ ████║    ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝
 ██║  ██║██╔████╔██║    ███████╗ ╚████╔╝ ██╔██╗ ██║██║
 ██║  ██║██║╚██╔╝██║    ╚════██║  ╚██╔╝  ██║╚██╗██║██║
 ██████╔╝██║ ╚═╝ ██║    ███████║   ██║   ██║ ╚████║╚██████╗
 ╚═════╝ ╚═╝     ╚═╝    ╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝
""".strip('\n')


def print_header():
    """Print the ASCII header with diagonal gradient. Call once after clear_screen()."""
    lines = ASCII_HEADER.split('\n')
    total = len(lines)

    for row, line in enumerate(lines):
        result = []
        for col, char in enumerate(line):
            if char != ' ':
                # Diagonal gradient: combine row and column position
                pos = (row / total) * 0.4 + (col / len(line)) * 0.6
                r, g, b = get_gradient_color(pos)
                result.append(f"{rgb(r, g, b)}{char}")
            else:
                result.append(char)
        print(''.join(result) + Colors.RESET)
    print()


# ============================================================================
# Box Drawing
# ============================================================================

BOX_TL, BOX_TR, BOX_BL, BOX_BR = "╭", "╮", "╰", "╯"
BOX_H, BOX_V, BOX_TL_DIV, BOX_TR_DIV = "─", "│", "├", "┤"


def _box_row(left: str, fill: str, right: str, width: int, color: str) -> str:
    return f"{color}{left}{fill * (width - 2)}{right}{Colors.RESET}"


# ============================================================================
# Menu Components
# ============================================================================

@dataclass
class MenuItem:
    label: str
    hotkey: str | None = None
    value: Any = None
    description: str | None = None

    def __post_init__(self):
        if self.value is None:
            self.value = self.label


@dataclass
class MenuDivider:
    pass


@dataclass
class MenuAction(MenuItem):
    pass


def check_resize() -> bool:
    """Check and clear the resize flag. Returns True if resize occurred."""
    global _resize_flag
    if _resize_flag:
        _resize_flag = False
        return True
    return False


@dataclass
class Menu:
    """Interactive terminal menu with arrow key navigation."""

    title: str = ""
    footer: str = ""
    items: list = field(default_factory=list)
    _selected: int = 0

    def add_item(self, item):
        self.items.append(item)

    def _selectable(self) -> list[int]:
        return [i for i, item in enumerate(self.items) if isinstance(item, (MenuItem, MenuAction))]

    def _width(self) -> int:
        w = 40
        if self.title:
            w = max(w, len(self.title) + 8)
        for item in self.items:
            if isinstance(item, (MenuItem, MenuAction)):
                length = len(item.label) + (len(item.description) + 3 if item.description else 0) + 8
                w = max(w, length)
        return min(w + 4, shutil.get_terminal_size().columns - 2)

    def _render(self):
        """Clear screen and render the full menu."""
        clear_screen()
        print_header()

        w = self._width()
        c = Colors.INDIGO

        # Box top
        print(_box_row(BOX_TL, BOX_H, BOX_TR, w, c))

        # Title
        if self.title:
            pad = w - 4 - len(self.title)
            left = pad // 2
            print(f"{c}{BOX_V}{Colors.RESET} {' ' * left}{Colors.BOLD}{self.title}{Colors.RESET}{' ' * (pad - left)} {c}{BOX_V}{Colors.RESET}")
            print(_box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))

        # Items
        for i, item in enumerate(self.items):
            if isinstance(item, MenuDivider):
                print(_box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))
            elif isinstance(item, (MenuItem, MenuAction)):
                selected = (i == self._selected)

                # Build content
                hotkey = f"{Colors.HOTKEY}[{item.hotkey}]{Colors.RESET} " if item.hotkey else "    "
                label = item.label
                if item.description:
                    label += f" {Colors.MUTED}({item.description}){Colors.RESET}"

                if selected:
                    content = f"{Colors.PINK}▸{Colors.RESET} {hotkey}{Colors.BOLD}{label}{Colors.RESET}"
                else:
                    content = f"  {hotkey}{label}"

                visible = len(strip_ansi(content))
                pad = w - 4 - visible
                print(f"{c}{BOX_V}{Colors.RESET} {content}{' ' * pad} {c}{BOX_V}{Colors.RESET}")

        # Footer
        if self.footer:
            print(_box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))
            pad = w - 4 - len(self.footer)
            left = pad // 2
            print(f"{c}{BOX_V}{Colors.RESET} {' ' * left}{Colors.MUTED}{self.footer}{Colors.RESET}{' ' * (pad - left)} {c}{BOX_V}{Colors.RESET}")

        # Box bottom
        print(_box_row(BOX_BL, BOX_H, BOX_BR, w, c))

        # Hint
        print(f"  {Colors.MUTED}↑/↓ Navigate  {Colors.HOTKEY}Enter{Colors.MUTED} Select  {Colors.HOTKEY}Esc{Colors.MUTED} Cancel{Colors.RESET}")

    def run(self, initial_selection: int = 0) -> tuple[MenuItem | MenuAction | None, int]:
        """Run menu, returns (selected item, selection index) or (None, index) if cancelled."""
        selectable = self._selectable()
        if not selectable:
            return None, 0

        # Start at initial_selection if valid, otherwise first item
        if initial_selection < len(selectable):
            self._selected = selectable[initial_selection]
        else:
            self._selected = selectable[0]

        hotkeys = {item.hotkey.upper(): i for i, item in enumerate(self.items)
                   if isinstance(item, (MenuItem, MenuAction)) and item.hotkey}

        # Clear any pending resize flag and render
        check_resize()
        self._render()

        while True:
            # Check for terminal resize (via SIGWINCH)
            if check_resize():
                self._render()
                continue

            key = getch(return_special_keys=True)

            # Check again after getch (signal may have interrupted it)
            if check_resize():
                self._render()
                continue

            if key == KEY_ESC:
                return None, selectable.index(self._selected)

            elif key == KEY_UP:
                pos = selectable.index(self._selected)
                if pos > 0:
                    self._selected = selectable[pos - 1]
                    self._render()

            elif key == KEY_DOWN:
                pos = selectable.index(self._selected)
                if pos < len(selectable) - 1:
                    self._selected = selectable[pos + 1]
                    self._render()

            elif key == KEY_ENTER:
                return self.items[self._selected], selectable.index(self._selected)

            elif isinstance(key, str) and len(key) == 1:
                upper = key.upper()
                if upper in hotkeys:
                    self._selected = hotkeys[upper]
                    return self.items[self._selected], selectable.index(self._selected)
                if key.isdigit() and key != '0':
                    idx = int(key)
                    if idx <= len(selectable):
                        self._selected = selectable[idx - 1]
                        return self.items[self._selected], selectable.index(self._selected)
