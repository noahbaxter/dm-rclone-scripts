"""
User interface components for DM Chart Sync.

Handles menu display, user input, and terminal operations.
"""

from pathlib import Path

from .utils import format_size, clear_screen
from .menu import Menu, MenuItem, MenuDivider, MenuResult
from .config import UserSettings, extract_subfolders_from_manifest
from .sync_ops import get_sync_status


def show_main_menu(folders: list, user_settings: UserSettings = None, selected_index: int = 0, download_path: Path = None) -> tuple[str, str | int | None, int]:
    """
    Show main menu and get user selection.

    Args:
        folders: List of folder dicts from manifest
        user_settings: User settings for checking charter enabled states
        selected_index: Index to keep selected (for maintaining position after toggle)
        download_path: Path to download folder for sync status calculation

    Returns tuple of (action, value, menu_position):
        - ("quit", None, pos) - user wants to quit
        - ("download", None, pos) - download all enabled
        - ("purge", None, pos) - purge extra files
        - ("configure", index, pos) - configure specific drive (enter on drive)
        - ("toggle", index, pos) - toggle drive on/off (space on drive)
    """
    # Calculate sync status for subtitle
    subtitle = ""
    if download_path and folders:
        status = get_sync_status(folders, download_path, user_settings)
        if status.total_charts > 0:
            pct = (status.synced_charts / status.total_charts) * 100
            if status.is_synced:
                subtitle = f"Synced: {status.synced_charts:,} charts ({format_size(status.synced_size)})"
            else:
                subtitle = f"Synced: {pct:.0f}% ({status.synced_charts:,}/{status.total_charts:,} charts, {format_size(status.missing_size)} remaining)"

    menu = Menu(title="Available chart packs:", subtitle=subtitle, space_hint="Toggle")

    # Add folder items with number hotkeys
    for i, folder in enumerate(folders, 1):
        folder_id = folder.get("folder_id", "")

        # Check if drive is enabled at top level
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        # Build stats string
        stats_parts = []

        # Calculate enabled charts/size based on charter selection
        charters = extract_subfolders_from_manifest(folder)
        charter_stats = {sf.get("name"): sf for sf in folder.get("subfolders", [])}

        if charters and user_settings:
            enabled_charters = [
                c for c in charters
                if user_settings.is_subfolder_enabled(folder_id, c)
            ]

            # Sum charts and size from enabled charters only
            enabled_charts = sum(
                charter_stats.get(c, {}).get("charts", {}).get("total", 0)
                for c in enabled_charters
            )
            enabled_size = sum(
                charter_stats.get(c, {}).get("total_size", 0)
                for c in enabled_charters
            )
            total_charts = folder.get("chart_count", 0)

            if total_charts:
                stats_parts.append(f"{enabled_charts}/{total_charts} charts")
            stats_parts.append(f"{len(enabled_charters)}/{len(charters)} charters")
            if enabled_size:
                stats_parts.append(format_size(enabled_size))
        else:
            # No charters or settings, show totals
            chart_count = folder.get("chart_count", 0)
            total_size = folder.get("total_size", 0)
            if chart_count:
                stats_parts.append(f"{chart_count} charts")
            if total_size:
                stats_parts.append(format_size(total_size))

        stats = ", ".join(stats_parts) if stats_parts else None

        # Use 1-9 for first 9 folders (store 0-based index)
        hotkey = str(i) if i <= 9 else None
        menu.add_item(MenuItem(
            folder['name'],
            hotkey=hotkey,
            value=i - 1,
            description=stats,
            disabled=not drive_enabled
        ))

    # Divider before actions
    menu.add_item(MenuDivider())

    # Action items
    menu.add_item(MenuItem("Download", hotkey="D", value=("download", None)))
    menu.add_item(MenuItem("Purge", hotkey="X", value=("purge", None)))
    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Quit", hotkey="Q", value=("quit", None)))

    result = menu.run(initial_index=selected_index)
    if result is None:
        return ("quit", None, selected_index)

    # Get position to restore (use pre-hotkey position for hotkey actions)
    restore_pos = menu._selected_before_hotkey if menu._selected_before_hotkey != menu._selected else menu._selected

    # Handle drive items (numbered items have int index as value)
    if isinstance(result.value, int):
        if result.action == "space":
            return ("toggle", result.value, menu._selected)
        else:  # enter
            return ("configure", result.value, menu._selected)

    # Handle action items (download, purge, quit) - restore to pre-hotkey position
    action, value = result.value
    return (action, value, restore_pos)


def show_subfolder_settings(folder: dict, user_settings: UserSettings, download_path: Path = None) -> bool:
    """
    Show toggle menu for charters within a drive.

    Args:
        folder: Folder dict from manifest
        user_settings: User settings to read/write toggle states
        download_path: Path to download folder for sync status calculation

    Returns True if settings were changed.
    """
    folder_id = folder.get("folder_id", "")
    folder_name = folder.get("name", "Unknown")
    charters = extract_subfolders_from_manifest(folder)

    if not charters:
        return False

    # Build lookup for charter stats from manifest
    charter_stats = {sf.get("name"): sf for sf in folder.get("subfolders", [])}

    changed = False
    selected_index = 0  # Track menu position to maintain after any action

    while True:
        # Check if drive is enabled
        drive_enabled = user_settings.is_drive_enabled(folder_id)

        # Calculate sync status for just this drive
        subtitle = ""
        if not drive_enabled:
            subtitle = "DRIVE DISABLED"
        elif download_path:
            status = get_sync_status([folder], download_path, user_settings)
            if status.total_charts > 0:
                pct = (status.synced_charts / status.total_charts) * 100
                if status.is_synced:
                    subtitle = f"Synced: {status.synced_charts:,} charts ({format_size(status.synced_size)})"
                else:
                    subtitle = f"Synced: {pct:.0f}% ({status.synced_charts:,}/{status.total_charts:,} charts)"

        menu = Menu(title=f"{folder_name} - Charters:", subtitle=subtitle, space_hint="Toggle")

        # Add charter toggle items (no hotkeys - too many charters)
        for i, charter_name in enumerate(charters):
            charter_enabled = user_settings.is_subfolder_enabled(folder_id, charter_name)

            # Get charter stats
            stats = charter_stats.get(charter_name, {})
            chart_count = stats.get("charts", {}).get("total", 0)
            total_size = stats.get("total_size", 0)

            # Build description
            desc_parts = []
            if chart_count:
                desc_parts.append(f"{chart_count} charts")
            if total_size:
                desc_parts.append(format_size(total_size))
            description = ", ".join(desc_parts) if desc_parts else None

            # If drive is disabled, all items appear disabled (greyed out)
            # show_toggle only shows colored [ON] when drive is also enabled
            item_disabled = not charter_enabled or not drive_enabled
            show_toggle_colored = charter_enabled and drive_enabled

            menu.add_item(MenuItem(charter_name, value=("toggle", i, charter_name), description=description, disabled=item_disabled, show_toggle=show_toggle_colored))

        menu.add_item(MenuDivider())

        # Show Enable Drive option if drive is disabled
        if not drive_enabled:
            menu.add_item(MenuItem("Enable Drive", hotkey="R", value=("enable_drive", None, None)))
            menu.add_item(MenuDivider())

        menu.add_item(MenuItem("Enable ALL", hotkey="E", value=("enable_all", None, None)))
        menu.add_item(MenuItem("Disable ALL", hotkey="D", value=("disable_all", None, None)))
        menu.add_item(MenuDivider())
        menu.add_item(MenuItem("Back", hotkey="B", value=("back", None, None)))

        result = menu.run(initial_index=selected_index)

        if result is None or result.value[0] == "back":
            break

        action, idx, charter_name = result.value

        if action == "enable_drive":
            # Re-enable the drive
            selected_index = menu._selected_before_hotkey
            user_settings.enable_drive(folder_id)
            user_settings.save()
            changed = True

        elif action == "enable_all":
            # Use position before hotkey was pressed
            selected_index = menu._selected_before_hotkey
            user_settings.enable_all(folder_id, charters)
            user_settings.save()
            changed = True

        elif action == "disable_all":
            # Use position before hotkey was pressed
            selected_index = menu._selected_before_hotkey
            user_settings.disable_all(folder_id, charters)
            user_settings.save()
            changed = True

        elif action == "toggle":
            # Keep current position for toggle actions
            selected_index = menu._selected
            user_settings.toggle_subfolder(folder_id, charter_name)
            user_settings.save()
            changed = True

    return changed


