"""
Interactive menu widget.

Provides terminal menus with arrow key navigation, scrolling, and hotkeys.
"""

import signal
import shutil
from dataclasses import dataclass, field
from typing import Any

from ..primitives import (
    getch,
    cbreak_noecho,
    clear_screen,
    Colors,
    KEY_UP,
    KEY_DOWN,
    KEY_LEFT,
    KEY_RIGHT,
    KEY_PAGE_UP,
    KEY_PAGE_DOWN,
    KEY_ENTER,
    KEY_ESC,
    KEY_SPACE,
)
from ..components import (
    box_row,
    strip_ansi,
    print_header,
    BOX_TL,
    BOX_TR,
    BOX_BL,
    BOX_BR,
    BOX_H,
    BOX_V,
    BOX_TL_DIV,
    BOX_TR_DIV,
)


# Global flag for resize detection
_resize_flag = False


def _handle_resize(signum, frame):
    """Signal handler for terminal resize (SIGWINCH)."""
    global _resize_flag
    _resize_flag = True


# Install signal handler (Unix only)
if hasattr(signal, 'SIGWINCH'):
    signal.signal(signal.SIGWINCH, _handle_resize)


def check_resize() -> bool:
    """Check and clear the resize flag. Returns True if resize occurred."""
    global _resize_flag
    if _resize_flag:
        _resize_flag = False
        return True
    return False


@dataclass
class MenuItem:
    """A selectable menu item."""
    label: str
    hotkey: str | None = None
    value: Any = None
    description: str | None = None
    disabled: bool = False
    show_toggle: bool | None = None
    pinned: bool = False

    def __post_init__(self):
        if self.value is None:
            self.value = self.label


@dataclass
class MenuDivider:
    """A visual divider between menu items."""
    pinned: bool = False


@dataclass
class MenuGroupHeader:
    """A collapsible group header in the menu."""
    label: str
    group_name: str
    expanded: bool = False
    value: Any = None
    drive_count: int = 0
    enabled_count: int = 0

    def __post_init__(self):
        if self.value is None:
            self.value = ("group", self.group_name)


@dataclass
class MenuAction(MenuItem):
    """A menu action item (alias for MenuItem)."""
    pass


@dataclass
class MenuResult:
    """Result from menu selection."""
    item: MenuItem | MenuAction
    action: str  # "enter" or "space"

    @property
    def value(self):
        return self.item.value


@dataclass
class Menu:
    """Interactive terminal menu with arrow key navigation."""

    title: str = ""
    subtitle: str = ""
    footer: str = ""
    space_hint: str = ""
    esc_label: str = "Back"
    items: list = field(default_factory=list)
    _selected: int = 0
    _selected_before_hotkey: int = 0
    _scroll_offset: int = 0

    def add_item(self, item):
        self.items.append(item)

    def _split_items(self) -> tuple[list[tuple[int, Any]], list[tuple[int, Any]]]:
        """Split items into scrollable and pinned lists, preserving original indices."""
        scrollable = []
        pinned = []
        for i, item in enumerate(self.items):
            is_pinned = getattr(item, 'pinned', False)
            if is_pinned:
                pinned.append((i, item))
            else:
                scrollable.append((i, item))
        return scrollable, pinned

    def _base_visible_capacity(self) -> int:
        """Calculate base capacity for scrollable items (without scroll indicators)."""
        term_height = shutil.get_terminal_size().lines
        fixed_lines = 8 + 4 + 1 + 1  # Header + box + hint + buffer
        if self.subtitle:
            fixed_lines += 1
        if self.footer:
            fixed_lines += 2
        _, pinned = self._split_items()
        fixed_lines += len(pinned)
        available = term_height - fixed_lines
        return max(5, available)

    def _visible_items_for_scroll(self, total_scrollable: int, scroll_offset: int) -> int:
        """Calculate visible items based on which scroll indicators will appear."""
        base = self._base_visible_capacity()

        if total_scrollable <= base:
            return base

        has_above = scroll_offset > 0
        has_below = scroll_offset + (base - 1) < total_scrollable

        if has_above and has_below:
            return base - 2
        else:
            return base - 1

    def _adjust_scroll(self):
        """Adjust scroll offset to keep selected item visible within scrollable items."""
        scrollable, _ = self._split_items()
        if not scrollable:
            self._scroll_offset = 0
            return

        total = len(scrollable)
        max_visible = self._visible_items_for_scroll(total, self._scroll_offset)

        selected_scroll_pos = None
        for pos, (orig_idx, _) in enumerate(scrollable):
            if orig_idx == self._selected:
                selected_scroll_pos = pos
                break

        if selected_scroll_pos is None:
            return

        if selected_scroll_pos < self._scroll_offset:
            self._scroll_offset = selected_scroll_pos
        elif selected_scroll_pos >= self._scroll_offset + max_visible:
            self._scroll_offset = selected_scroll_pos - max_visible + 1

        max_visible = self._visible_items_for_scroll(total, self._scroll_offset)
        max_scroll = max(0, total - max_visible)
        self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

    def _selectable(self) -> list[int]:
        return [i for i, item in enumerate(self.items) if isinstance(item, (MenuItem, MenuAction, MenuGroupHeader))]

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
            elif isinstance(item, MenuGroupHeader):
                w = max(w, len(item.label) + 10)
        return min(w + 4, shutil.get_terminal_size().columns - 2)

    def _render_item(self, orig_idx: int, item: Any, w: int, c: str):
        """Render a single menu item."""
        if isinstance(item, MenuDivider):
            print(box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))
        elif isinstance(item, MenuGroupHeader):
            selected = (orig_idx == self._selected)
            indicator = "▼" if item.expanded else "▶"
            label_upper = item.label.upper()
            count_str = ""
            if not item.expanded and item.drive_count > 0:
                count_str = f" {Colors.MUTED}({item.enabled_count}/{item.drive_count} drives){Colors.RESET}"
            if selected:
                content = f"{Colors.PINK}▸{Colors.RESET} {Colors.MUTED}{indicator}{Colors.RESET} {Colors.HOTKEY}[{label_upper}]{Colors.RESET}{count_str}"
            else:
                content = f"  {Colors.MUTED}{indicator}{Colors.RESET} {Colors.HOTKEY}[{label_upper}]{Colors.RESET}{count_str}"
            visible = len(strip_ansi(content))
            pad = w - 4 - visible
            print(f"{c}{BOX_V}{Colors.RESET} {content}{' ' * pad} {c}{BOX_V}{Colors.RESET}")
        elif isinstance(item, (MenuItem, MenuAction)):
            selected = (orig_idx == self._selected)
            is_disabled = getattr(item, 'disabled', False)
            show_toggle = getattr(item, 'show_toggle', None)

            if show_toggle is not None:
                toggle_prefix = f"{Colors.HOTKEY}[ON]{Colors.RESET}  " if show_toggle else f"{Colors.DIM}[OFF]{Colors.RESET} "
                toggle_len = 6
            else:
                toggle_prefix = ""
                toggle_len = 0

            hotkey_len = len(item.hotkey) + 3 if item.hotkey else 0
            desc_len = len(item.description) + 3 if item.description else 0
            prefix_len = 2

            max_label_len = w - 4 - prefix_len - toggle_len - hotkey_len - desc_len - 1
            label_text = item.label
            if len(label_text) > max_label_len and max_label_len > 3:
                label_text = label_text[:max_label_len - 3] + "..."

            if is_disabled:
                if selected:
                    hotkey = f"{Colors.DIM_HOVER}[{item.hotkey}]{Colors.RESET} " if item.hotkey else ""
                    label = f"{Colors.DIM_HOVER}{label_text}{Colors.RESET}"
                    if item.description:
                        label += f" {Colors.MUTED_DIM}({item.description}){Colors.RESET}"
                    content = f"{Colors.PINK}▸{Colors.RESET} {toggle_prefix}{hotkey}{label}"
                else:
                    hotkey = f"{Colors.DIM}[{item.hotkey}]{Colors.RESET} " if item.hotkey else ""
                    label = f"{Colors.DIM}{label_text}{Colors.RESET}"
                    if item.description:
                        label += f" {Colors.MUTED_DIM}({item.description}){Colors.RESET}"
                    content = f"  {toggle_prefix}{hotkey}{label}"
            else:
                hotkey = f"{Colors.HOTKEY}[{item.hotkey}]{Colors.RESET} " if item.hotkey else ""
                label = label_text
                if item.description:
                    label += f" {Colors.MUTED}({item.description}){Colors.RESET}"
                if selected:
                    content = f"{Colors.PINK}▸{Colors.RESET} {toggle_prefix}{hotkey}{Colors.BOLD}{label}{Colors.RESET}"
                else:
                    content = f"  {toggle_prefix}{hotkey}{label}"

            visible = len(strip_ansi(content))
            pad = max(0, w - 4 - visible)
            print(f"{c}{BOX_V}{Colors.RESET} {content}{' ' * pad} {c}{BOX_V}{Colors.RESET}")

    def _render(self):
        """Clear screen and render the full menu."""
        clear_screen()
        print_header()

        w = self._width()
        c = Colors.INDIGO

        scrollable, pinned = self._split_items()
        self._adjust_scroll()
        total = len(scrollable)
        max_visible = self._visible_items_for_scroll(total, self._scroll_offset)
        visible_start = self._scroll_offset
        visible_end = min(total, visible_start + max_visible)
        has_more_above = visible_start > 0
        has_more_below = visible_end < total

        # Box top
        print(box_row(BOX_TL, BOX_H, BOX_TR, w, c))

        # Title
        if self.title:
            pad = w - 4 - len(self.title)
            left = pad // 2
            print(f"{c}{BOX_V}{Colors.RESET} {' ' * left}{Colors.BOLD}{self.title}{Colors.RESET}{' ' * (pad - left)} {c}{BOX_V}{Colors.RESET}")
            if self.subtitle:
                sub_pad = w - 4 - len(strip_ansi(self.subtitle))
                sub_left = sub_pad // 2
                print(f"{c}{BOX_V}{Colors.RESET} {' ' * sub_left}{Colors.MUTED}{self.subtitle}{Colors.RESET}{' ' * (sub_pad - sub_left)} {c}{BOX_V}{Colors.RESET}")
            print(box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))

        # Scroll indicator (more above)
        if has_more_above:
            indicator = f"{Colors.MUTED}  ▲ {visible_start} more above{Colors.RESET}"
            vis_len = len(strip_ansi(indicator))
            pad = w - 4 - vis_len
            print(f"{c}{BOX_V}{Colors.RESET} {indicator}{' ' * pad} {c}{BOX_V}{Colors.RESET}")

        # Render visible scrollable items
        for scroll_idx in range(visible_start, visible_end):
            orig_idx, item = scrollable[scroll_idx]
            self._render_item(orig_idx, item, w, c)

        # Scroll indicator (more below)
        if has_more_below:
            remaining = len(scrollable) - visible_end
            indicator = f"{Colors.MUTED}  ▼ {remaining} more below{Colors.RESET}"
            vis_len = len(strip_ansi(indicator))
            pad = w - 4 - vis_len
            print(f"{c}{BOX_V}{Colors.RESET} {indicator}{' ' * pad} {c}{BOX_V}{Colors.RESET}")

        # Render pinned items
        for orig_idx, item in pinned:
            self._render_item(orig_idx, item, w, c)

        # Footer
        if self.footer:
            print(box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))
            footer_len = len(strip_ansi(self.footer))
            pad = w - 4 - footer_len
            left = pad // 2
            print(f"{c}{BOX_V}{Colors.RESET} {' ' * left}{self.footer}{' ' * (pad - left)} {c}{BOX_V}{Colors.RESET}")

        # Box bottom
        print(box_row(BOX_BL, BOX_H, BOX_BR, w, c))

        # Hint
        hint = f"  {Colors.MUTED}↑/↓ Navigate  {Colors.HOTKEY}Enter{Colors.MUTED} Select"
        if self.space_hint:
            hint += f"  {Colors.HOTKEY}Space{Colors.MUTED} {self.space_hint}"
        hint += f"  {Colors.HOTKEY}Esc{Colors.MUTED} {self.esc_label}{Colors.RESET}"
        print(hint)

    def run(self, initial_index: int = 0) -> MenuResult | None:
        """Run menu, returns MenuResult or None if cancelled."""
        selectable = self._selectable()
        if not selectable:
            return None

        if initial_index in selectable:
            self._selected = initial_index
        else:
            self._selected = selectable[0]

        self._scroll_offset = 0
        self._adjust_scroll()

        hotkeys = {item.hotkey.upper(): i for i, item in enumerate(self.items)
                   if isinstance(item, (MenuItem, MenuAction)) and item.hotkey}

        with cbreak_noecho():
            check_resize()
            self._render()

            while True:
                if check_resize():
                    self._render()
                    continue

                key = getch(return_special_keys=True)

                if check_resize():
                    self._render()
                    continue

                if key == KEY_ESC:
                    return None

                elif key == KEY_UP:
                    pos = selectable.index(self._selected)
                    if pos > 0:
                        self._selected = selectable[pos - 1]
                    else:
                        self._selected = selectable[-1]
                    self._render()

                elif key == KEY_DOWN:
                    pos = selectable.index(self._selected)
                    if pos < len(selectable) - 1:
                        self._selected = selectable[pos + 1]
                    else:
                        self._selected = selectable[0]
                    self._render()

                elif key == KEY_PAGE_UP:
                    pos = selectable.index(self._selected)
                    scrollable, _ = self._split_items()
                    page_size = max(1, self._base_visible_capacity() - 2)
                    new_pos = max(0, pos - page_size)
                    self._selected = selectable[new_pos]
                    self._render()

                elif key == KEY_PAGE_DOWN:
                    pos = selectable.index(self._selected)
                    scrollable, _ = self._split_items()
                    page_size = max(1, self._base_visible_capacity() - 2)
                    new_pos = min(len(selectable) - 1, pos + page_size)
                    self._selected = selectable[new_pos]
                    self._render()

                elif key == KEY_ENTER:
                    return MenuResult(self.items[self._selected], "enter")

                elif key == KEY_SPACE:
                    return MenuResult(self.items[self._selected], "space")

                elif key == KEY_LEFT or key == KEY_RIGHT:
                    current_item = self.items[self._selected]
                    if isinstance(current_item, MenuGroupHeader):
                        return MenuResult(current_item, "enter")

                elif isinstance(key, str) and len(key) == 1:
                    upper = key.upper()
                    if upper in hotkeys:
                        self._selected_before_hotkey = self._selected
                        self._selected = hotkeys[upper]
                        return MenuResult(self.items[self._selected], "enter")
                    if key.isdigit() and key != '0':
                        idx = int(key)
                        if idx <= len(selectable):
                            self._selected = selectable[idx - 1]
                            return MenuResult(self.items[self._selected], "enter")
