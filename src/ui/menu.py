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

from .keyboard import getch, KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_SPACE
from .colors import Colors, rgb, lerp_color
from ..utils import clear_screen


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
    disabled: bool = False  # If True, render with grey/dim style
    show_toggle: bool | None = None  # If set, show [ON]/[OFF] indicator

    def __post_init__(self):
        if self.value is None:
            self.value = self.label


@dataclass
class MenuDivider:
    pass


@dataclass
class MenuAction(MenuItem):
    pass


@dataclass
class MenuResult:
    """Result from menu selection."""
    item: MenuItem | MenuAction
    action: str  # "enter" or "space"

    @property
    def value(self):
        return self.item.value


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
    subtitle: str = ""  # Status line below title
    footer: str = ""
    space_hint: str = ""  # Hint for spacebar action, e.g. "Toggle"
    items: list = field(default_factory=list)
    _selected: int = 0
    _selected_before_hotkey: int = 0  # Position before hotkey was pressed

    def add_item(self, item):
        self.items.append(item)

    def _selectable(self) -> list[int]:
        return [i for i, item in enumerate(self.items) if isinstance(item, (MenuItem, MenuAction))]

    def _width(self) -> int:
        w = 40
        if self.title:
            w = max(w, len(self.title) + 8)
        if self.subtitle:
            w = max(w, len(self.subtitle) + 8)
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
            # Subtitle (status line)
            if self.subtitle:
                sub_pad = w - 4 - len(strip_ansi(self.subtitle))
                sub_left = sub_pad // 2
                print(f"{c}{BOX_V}{Colors.RESET} {' ' * sub_left}{Colors.MUTED}{self.subtitle}{Colors.RESET}{' ' * (sub_pad - sub_left)} {c}{BOX_V}{Colors.RESET}")
            print(_box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))

        # Items
        for i, item in enumerate(self.items):
            if isinstance(item, MenuDivider):
                print(_box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))
            elif isinstance(item, (MenuItem, MenuAction)):
                selected = (i == self._selected)
                is_disabled = getattr(item, 'disabled', False)

                # Build content based on enabled/disabled and selected state
                show_toggle = getattr(item, 'show_toggle', None)

                # Build toggle prefix if needed
                if show_toggle is not None:
                    if show_toggle:
                        toggle_prefix = f"{Colors.HOTKEY}[ON]{Colors.RESET}  "
                    else:
                        toggle_prefix = f"{Colors.DIM}[OFF]{Colors.RESET} "
                else:
                    toggle_prefix = ""

                if is_disabled:
                    # Disabled items - dimmed text and darker description
                    if selected:
                        # Slightly brighter text when hovered
                        hotkey = f"{Colors.DIM_HOVER}[{item.hotkey}]{Colors.RESET} " if item.hotkey else ""
                        label = f"{Colors.DIM_HOVER}{item.label}{Colors.RESET}"
                        if item.description:
                            label += f" {Colors.MUTED_DIM}({item.description}){Colors.RESET}"
                        content = f"{Colors.PINK_DIM}▸{Colors.RESET} {toggle_prefix}{hotkey}{label}"
                    else:
                        hotkey = f"{Colors.DIM}[{item.hotkey}]{Colors.RESET} " if item.hotkey else ""
                        label = f"{Colors.DIM}{item.label}{Colors.RESET}"
                        if item.description:
                            label += f" {Colors.MUTED_DIM}({item.description}){Colors.RESET}"
                        content = f"  {toggle_prefix}{hotkey}{label}"
                else:
                    # Enabled items - normal colors
                    hotkey = f"{Colors.HOTKEY}[{item.hotkey}]{Colors.RESET} " if item.hotkey else ""
                    label = item.label
                    if item.description:
                        label += f" {Colors.MUTED}({item.description}){Colors.RESET}"

                    if selected:
                        content = f"{Colors.PINK}▸{Colors.RESET} {toggle_prefix}{hotkey}{Colors.BOLD}{label}{Colors.RESET}"
                    else:
                        content = f"  {toggle_prefix}{hotkey}{label}"

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
        hint = f"  {Colors.MUTED}↑/↓ Navigate  {Colors.HOTKEY}Enter{Colors.MUTED} Select"
        if self.space_hint:
            hint += f"  {Colors.HOTKEY}Space{Colors.MUTED} {self.space_hint}"
        hint += f"  {Colors.HOTKEY}Esc{Colors.MUTED} Cancel{Colors.RESET}"
        print(hint)

    def run(self, initial_index: int = 0) -> MenuResult | None:
        """Run menu, returns MenuResult or None if cancelled.

        Args:
            initial_index: Index to start selection at (for maintaining position)
        """
        selectable = self._selectable()
        if not selectable:
            return None

        # Use initial_index if valid, otherwise start at first item
        if initial_index in selectable:
            self._selected = initial_index
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
                return None

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
                return MenuResult(self.items[self._selected], "enter")

            elif key == KEY_SPACE:
                return MenuResult(self.items[self._selected], "space")

            elif isinstance(key, str) and len(key) == 1:
                upper = key.upper()
                if upper in hotkeys:
                    self._selected_before_hotkey = self._selected  # Save position before hotkey
                    self._selected = hotkeys[upper]
                    return MenuResult(self.items[self._selected], "enter")
                if key.isdigit() and key != '0':
                    idx = int(key)
                    if idx <= len(selectable):
                        self._selected = selectable[idx - 1]
                        return MenuResult(self.items[self._selected], "enter")
