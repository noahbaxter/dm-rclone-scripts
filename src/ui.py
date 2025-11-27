"""
User interface components for DM Chart Sync.

Handles menu display, user input, and terminal operations.
"""

import os

from .utils import format_size
from .menu import Menu, MenuItem, MenuDivider


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def show_main_menu(folders: list, selected_index: int = 0) -> tuple[str, int]:
    """
    Show main menu and get user selection.

    Args:
        folders: List of folder dicts
        selected_index: Index to start selection at

    Returns:
        Tuple of (selection string, new selected index)
    """
    menu = Menu(title="Available chart packs:")

    # Add folder items with number hotkeys
    for i, folder in enumerate(folders, 1):
        file_count = folder.get("file_count", 0)
        total_size = folder.get("total_size", 0)
        if file_count and total_size:
            stats = f"{file_count} files, {format_size(total_size)}"
        else:
            stats = None

        # Use 1-9 for first 9 folders
        hotkey = str(i) if i <= 9 else None
        menu.add_item(MenuItem(folder['name'], hotkey=hotkey, value=str(i), description=stats))

    # Divider before actions
    menu.add_item(MenuDivider())

    # Action items
    menu.add_item(MenuItem("Download ALL", hotkey="A", value="A"))
    menu.add_item(MenuItem("Purge extra files", hotkey="X", value="X"))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Quit", hotkey="Q", value="Q"))

    result, new_index = menu.run(selected_index)
    if result is None:
        return "Q", new_index  # ESC = quit from main menu
    return result.value, new_index


