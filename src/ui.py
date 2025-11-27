"""
User interface components for DM Chart Sync.

Handles menu display, user input, and terminal operations.
"""

import os
import re
from pathlib import Path

from .config import UserConfig
from .drive_client import DriveClient
from .utils import format_size
from .keyboard import input_with_esc, wait_for_key, menu_input, CancelInput
from .menu import Menu, MenuItem, MenuDivider, MenuAction


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def extract_folder_id(url_or_id: str) -> str | None:
    """Extract folder ID from Google Drive URL or return as-is if already an ID."""
    match = re.search(r"folders/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
    if re.match(r"^[a-zA-Z0-9_-]+$", url_or_id):
        return url_or_id
    return None


def print_header():
    """Print application header."""
    print("=" * 50)
    print("  DM Chart Sync v2.0")
    print("  Download charts without any setup!")
    print("=" * 50)
    print()


def show_main_menu(folders: list, config: UserConfig) -> str:
    """
    Show main menu and get user selection.

    Returns selection string (hotkey value), or "Q" if ESC pressed.
    """
    menu = Menu(title="Available chart packs:")

    # Add folder items with number hotkeys
    for i, folder in enumerate(folders, 1):
        prefix = "[Official]" if folder.get("official", True) else "[Custom]"
        file_count = folder.get("file_count", 0)
        total_size = folder.get("total_size", 0)
        if file_count and total_size:
            stats = f"({file_count} files, {format_size(total_size)})"
        else:
            stats = ""

        # Use 1-9 for first 9 folders
        hotkey = str(i) if i <= 9 else None
        label = f"{prefix} {folder['name']}"
        if stats:
            label += f" {stats}"

        menu.add_item(MenuItem(label, hotkey=hotkey, value=str(i)))

    # Divider before actions
    menu.add_item(MenuDivider())

    # Action items
    menu.add_item(MenuItem("Download ALL", hotkey="A", value="A"))
    menu.add_item(MenuItem("Purge extra files (clean up)", hotkey="X", value="X"))
    menu.add_item(MenuItem("Add custom folder", hotkey="C", value="C"))

    if config.custom_folders:
        menu.add_item(MenuItem("Remove custom folder", hotkey="R", value="R"))

    menu.add_item(MenuItem(
        f"Change download path",
        hotkey="P",
        value="P",
        description=str(config.resolve_download_path())
    ))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Quit", hotkey="Q", value="Q"))

    result = menu.run()
    if result is None:
        return "Q"  # ESC = quit from main menu
    return result.value


def add_custom_folder(config: UserConfig, client: DriveClient) -> bool:
    """Prompt user to add a custom folder. Returns False if cancelled."""
    print("\n" + "-" * 40)
    print("Add Custom Folder (ESC to cancel)")
    print("-" * 40)
    print("Paste a Google Drive folder URL or ID.")
    print("Example: https://drive.google.com/drive/folders/1ABC123xyz")
    print()

    try:
        url_or_id = input_with_esc("Folder URL or ID: ")
    except CancelInput:
        return False

    if not url_or_id:
        return False

    folder_id = extract_folder_id(url_or_id)
    if not folder_id:
        print("Error: Invalid folder URL or ID")
        try:
            wait_for_key()
        except CancelInput:
            pass
        return False

    # Check for duplicates
    if config.get_custom_folder(folder_id):
        print("This folder is already in your list!")
        try:
            wait_for_key()
        except CancelInput:
            pass
        return False

    try:
        name = input_with_esc("Give this folder a name: ")
    except CancelInput:
        return False

    if not name:
        name = f"Custom Folder ({folder_id[:8]}...)"

    # Verify access
    print(f"\nVerifying access to folder...")
    files = client.list_folder(folder_id)
    if not files:
        print("Error: Could not access folder. Make sure it's shared as 'Anyone with link'")
        try:
            wait_for_key()
        except CancelInput:
            pass
        return False

    print(f"Success! Found {len(files)} items in folder.")

    config.add_custom_folder(name, folder_id)
    config.save()
    print(f"Added '{name}' to your folders!")
    try:
        wait_for_key()
    except CancelInput:
        pass
    return True


def remove_custom_folder(config: UserConfig) -> bool:
    """Prompt user to remove a custom folder. Returns False if cancelled."""
    if not config.custom_folders:
        print("No custom folders to remove.")
        try:
            wait_for_key()
        except CancelInput:
            pass
        return False

    menu = Menu(title="Remove Custom Folder")

    for i, folder in enumerate(config.custom_folders, 1):
        hotkey = str(i) if i <= 9 else None
        menu.add_item(MenuItem(folder.name, hotkey=hotkey, value=i - 1))

    result = menu.run()
    if result is None:
        return False

    idx = result.value
    if 0 <= idx < len(config.custom_folders):
        removed = config.custom_folders[idx]
        config.remove_custom_folder(removed.folder_id)
        config.save()
        print(f"Removed '{removed.name}'")
        try:
            wait_for_key()
        except CancelInput:
            pass
        return True

    return False


def change_download_path(config: UserConfig) -> bool:
    """Change the download directory. Returns False if cancelled."""
    print("\n" + "-" * 40)
    print("Change Download Path (ESC to cancel)")
    print("-" * 40)
    print(f"Current path: {config.download_path}")
    print(f"Resolves to: {config.resolve_download_path()}")
    print()
    print("Tips:")
    print("  - Use '~' for home directory (e.g., ~/Downloads)")
    print("  - Use a plain name to save next to the app (e.g., 'Charts')")
    print("  - Use an absolute path for a specific location")
    print()

    try:
        new_path = input_with_esc("Enter new path: ")
    except CancelInput:
        return False

    if new_path:
        config.download_path = new_path
        config.save()
        print(f"Download path set to: {new_path}")
        print(f"Resolves to: {config.resolve_download_path()}")
        try:
            wait_for_key()
        except CancelInput:
            pass

    return True


def show_purge_menu(all_folders: list) -> str:
    """Show purge menu and get selection. Returns 'C' if cancelled."""
    menu = Menu(
        title="Purge Extra Files",
        footer="Removes files not in manifest"
    )

    # Add official folders only
    for i, folder in enumerate(all_folders, 1):
        if folder.get("official"):
            hotkey = str(i) if i <= 9 else None
            menu.add_item(MenuItem(folder['name'], hotkey=hotkey, value=str(i)))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("All official folders", hotkey="A", value="A"))

    result = menu.run()
    if result is None:
        return "C"  # Cancel
    return result.value
