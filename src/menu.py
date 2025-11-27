"""
Menu system for DM Chart Sync.

Provides interactive terminal menus with in-place rendering.
"""

import sys
from dataclasses import dataclass, field
from typing import Any

from .keyboard import getch, KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC


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
    _selected_index: int = 0
    _last_render_height: int = 0

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

    def _render(self, first_render: bool = False):
        """
        Render the menu.

        On first render, just prints. On subsequent renders, moves cursor
        up to overwrite the previous render.
        """
        # Move cursor up to overwrite previous render
        if not first_render and self._last_render_height > 0:
            self._move_cursor_up(self._last_render_height)

        lines = []

        # Title
        if self.title:
            lines.append(self.title)

        # Items
        selectable = self._get_selectable_indices()
        for i, item in enumerate(self.items):
            if isinstance(item, MenuDivider):
                lines.append("")
            elif isinstance(item, (MenuItem, MenuAction)):
                # Build the line
                is_selected = (i == self._selected_index)

                # Cursor indicator
                cursor = ">" if is_selected else " "

                # Hotkey
                if item.hotkey:
                    hotkey_str = f"[{item.hotkey}]"
                else:
                    hotkey_str = "   "

                # Label with optional description
                label = item.label
                if item.description:
                    label += f" ({item.description})"

                line = f"  {cursor} {hotkey_str} {label}"
                lines.append(line)

        # Footer
        if self.footer:
            lines.append("")
            lines.append(self.footer)

        # Navigation hint
        lines.append("")
        lines.append("↑/↓: Navigate  Enter: Select  ESC: Cancel")

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
