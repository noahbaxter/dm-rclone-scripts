"""
User interface components for DM Chart Sync.

Handles menu display, user input, and terminal operations.
"""

from dataclasses import dataclass, field
from pathlib import Path

from ..utils import format_size, clear_screen
from ..config import UserSettings, DrivesConfig, extract_subfolders_from_manifest
from ..sync.operations import get_sync_status, count_purgeable_charts, SyncStatus
from .menu import Menu, MenuItem, MenuDivider, MenuGroupHeader, MenuResult, print_header


@dataclass
class MainMenuCache:
    """Cache for expensive main menu calculations."""
    # Global stats
    subtitle: str = ""
    purge_desc: str | None = None

    # Per-folder stats: {folder_id: description_string}
    folder_stats: dict = field(default_factory=dict)

    # Group enabled counts: {group_name: enabled_count}
    group_enabled_counts: dict = field(default_factory=dict)


def compute_main_menu_cache(
    folders: list,
    user_settings: UserSettings,
    download_path: Path,
    drives_config: DrivesConfig
) -> MainMenuCache:
    """
    Compute all expensive stats for the main menu.

    Call this once, then reuse for group expand/collapse operations.
    """
    cache = MainMenuCache()

    if not download_path or not folders:
        return cache

    # Calculate global sync status for subtitle
    raw_status = get_sync_status(folders, download_path, user_settings=None)
    enabled_status = get_sync_status(folders, download_path, user_settings)

    pct = (enabled_status.synced_charts / enabled_status.total_charts * 100) if enabled_status.total_charts > 0 else 0
    cache.subtitle = (
        f"Downloaded: {raw_status.synced_charts:,} charts ({format_size(raw_status.synced_size)}) | "
        f"Syncing: {enabled_status.total_charts:,} charts ({format_size(enabled_status.total_size)}) | "
        f"{pct:.0f}% synced"
    )

    # Calculate purge count
    purge_count, purge_size = count_purgeable_charts(folders, download_path, user_settings)
    if purge_count > 0:
        cache.purge_desc = f"{purge_count} charts, {format_size(purge_size)}"

    # Calculate per-folder stats
    for folder in folders:
        folder_id = folder.get("folder_id", "")
        stats_parts = []

        # Get sync status for this folder
        status = get_sync_status([folder], download_path, user_settings)

        # Show downloaded/total for enabled setlists
        if status.total_charts:
            stats_parts.append(f"{status.synced_charts}/{status.total_charts} charts")

        setlists = extract_subfolders_from_manifest(folder)
        if setlists and user_settings:
            enabled_setlists = [
                c for c in setlists
                if user_settings.is_subfolder_enabled(folder_id, c)
            ]
            stats_parts.append(f"{len(enabled_setlists)}/{len(setlists)} setlists")

        # Show downloaded size
        stats_parts.append(format_size(status.synced_size))

        cache.folder_stats[folder_id] = ", ".join(stats_parts) if stats_parts else None

    # Calculate group enabled counts
    if drives_config:
        for group_name in drives_config.get_groups():
            group_drives = drives_config.get_drives_in_group(group_name)
            enabled_count = sum(
                1 for d in group_drives
                if (user_settings.is_drive_enabled(d.folder_id) if user_settings else True)
            )
            cache.group_enabled_counts[group_name] = enabled_count

    return cache


def show_main_menu(
    folders: list,
    user_settings: UserSettings = None,
    selected_index: int = 0,
    download_path: Path = None,
    drives_config: DrivesConfig = None,
    cache: MainMenuCache = None
) -> tuple[str, str | int | None, int]:
    """
    Show main menu and get user selection.

    Args:
        folders: List of folder dicts from manifest
        user_settings: User settings for checking charter enabled states
        selected_index: Index to keep selected (for maintaining position after toggle)
        download_path: Path to download folder for sync status calculation
        drives_config: Drive configuration with group information
        cache: Pre-computed stats cache (if None, will compute fresh)

    Returns tuple of (action, value, menu_position):
        - ("quit", None, pos) - user wants to quit
        - ("download", None, pos) - download all enabled
        - ("purge", None, pos) - purge extra files
        - ("configure", folder_id, pos) - configure specific drive (enter on drive)
        - ("toggle", folder_id, pos) - toggle drive on/off (space on drive)
        - ("toggle_group", group_name, pos) - expand/collapse group
    """
    # Compute cache if not provided
    if cache is None:
        cache = compute_main_menu_cache(folders, user_settings, download_path, drives_config)

    menu = Menu(title="Available chart packs:", subtitle=cache.subtitle, space_hint="Toggle")

    # Build folder lookup by folder_id
    folder_lookup = {f.get("folder_id", ""): f for f in folders}

    # Build group membership from drives_config
    grouped_folder_ids = set()  # All folder_ids that belong to a group
    groups = []
    if drives_config:
        groups = drives_config.get_groups()
        for drive in drives_config.drives:
            if drive.group:
                grouped_folder_ids.add(drive.folder_id)

    # Track which folders we've added to the menu
    added_folders = set()
    hotkey_num = 1

    def add_folder_item(folder: dict, indent: bool = False):
        nonlocal hotkey_num
        folder_id = folder.get("folder_id", "")
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        stats = cache.folder_stats.get(folder_id)

        # Hotkeys only for first 9 ungrouped folders
        hotkey = None
        if not indent and hotkey_num <= 9:
            hotkey = str(hotkey_num)
            hotkey_num += 1

        label = f"  {folder['name']}" if indent else folder['name']
        menu.add_item(MenuItem(
            label,
            hotkey=hotkey,
            value=folder_id,
            description=stats,
            disabled=not drive_enabled
        ))
        added_folders.add(folder_id)

    # First, add ungrouped folders
    if drives_config:
        for drive in drives_config.get_ungrouped_drives():
            folder = folder_lookup.get(drive.folder_id)
            if folder:
                add_folder_item(folder)

    # Then add groups with their folders
    for group_name in groups:
        expanded = user_settings.is_group_expanded(group_name) if user_settings else False

        # Count drives and enabled drives in this group
        group_drives = drives_config.get_drives_in_group(group_name) if drives_config else []
        drive_count = len(group_drives)
        enabled_count = cache.group_enabled_counts.get(group_name, 0)

        menu.add_item(MenuGroupHeader(
            label=group_name,
            group_name=group_name,
            expanded=expanded,
            drive_count=drive_count,
            enabled_count=enabled_count
        ))

        for drive in group_drives:
            # Mark as added even if collapsed (so they don't appear separately)
            added_folders.add(drive.folder_id)
            if expanded:
                folder = folder_lookup.get(drive.folder_id)
                if folder:
                    add_folder_item(folder, indent=True)

    # Add any folders not in drives_config (fallback for manifest folders not in config)
    for folder in folders:
        folder_id = folder.get("folder_id", "")
        if folder_id not in added_folders:
            add_folder_item(folder)

    # Divider before actions
    menu.add_item(MenuDivider())

    # Action items
    menu.add_item(MenuItem("Download", hotkey="D", value=("download", None)))

    # Show purge count from cache
    menu.add_item(MenuItem("Purge", hotkey="X", value=("purge", None), description=cache.purge_desc))
    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Quit", hotkey="Q", value=("quit", None)))

    result = menu.run(initial_index=selected_index)
    if result is None:
        return ("quit", None, selected_index)

    # Get position to restore (use pre-hotkey position for hotkey actions)
    restore_pos = menu._selected_before_hotkey if menu._selected_before_hotkey != menu._selected else menu._selected

    # Handle group headers (expand/collapse)
    if isinstance(result.value, tuple) and len(result.value) == 2 and result.value[0] == "group":
        return ("toggle_group", result.value[1], menu._selected)

    # Handle drive items (folder_id strings)
    if isinstance(result.value, str) and not result.value.startswith(("download", "purge", "quit")):
        if result.action == "space":
            return ("toggle", result.value, menu._selected)
        else:  # enter
            return ("configure", result.value, menu._selected)

    # Handle action items (download, purge, quit) - restore to pre-hotkey position
    action, value = result.value
    return (action, value, restore_pos)


def show_subfolder_settings(folder: dict, user_settings: UserSettings, download_path: Path = None) -> bool:
    """
    Show toggle menu for setlists within a drive.

    Args:
        folder: Folder dict from manifest
        user_settings: User settings to read/write toggle states
        download_path: Path to download folder for sync status calculation

    Returns True if settings were changed.
    """
    folder_id = folder.get("folder_id", "")
    folder_name = folder.get("name", "Unknown")
    setlists = extract_subfolders_from_manifest(folder)

    if not setlists:
        return False

    # Build lookup for setlist stats from manifest
    setlist_stats = {sf.get("name"): sf for sf in folder.get("subfolders", [])}

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

        menu = Menu(title=f"{folder_name} - Setlists:", subtitle=subtitle, space_hint="Toggle")

        # Add setlist toggle items (no hotkeys - too many setlists)
        for i, setlist_name in enumerate(setlists):
            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)

            # Get setlist stats
            stats = setlist_stats.get(setlist_name, {})
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
            item_disabled = not setlist_enabled or not drive_enabled
            show_toggle_colored = setlist_enabled and drive_enabled

            menu.add_item(MenuItem(setlist_name, value=("toggle", i, setlist_name), description=description, disabled=item_disabled, show_toggle=show_toggle_colored))

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

        action, idx, setlist_name = result.value

        if action == "enable_drive":
            # Re-enable the drive
            selected_index = menu._selected_before_hotkey
            user_settings.enable_drive(folder_id)
            user_settings.save()
            changed = True

        elif action == "enable_all":
            # Use position before hotkey was pressed
            selected_index = menu._selected_before_hotkey
            user_settings.enable_all(folder_id, setlists)
            user_settings.save()
            changed = True

        elif action == "disable_all":
            # Use position before hotkey was pressed
            selected_index = menu._selected_before_hotkey
            user_settings.disable_all(folder_id, setlists)
            user_settings.save()
            changed = True

        elif action == "toggle":
            # Keep current position for toggle actions
            selected_index = menu._selected
            user_settings.toggle_subfolder(folder_id, setlist_name)
            user_settings.save()
            changed = True

    return changed


def show_confirmation(title: str, message: str = None) -> bool:
    """
    Show a Yes/No confirmation dialog.

    Args:
        title: The question to ask (e.g., "Are you sure you want to purge?")
        message: Optional additional context shown as subtitle

    Returns:
        True if user confirmed (Yes), False otherwise (No or cancelled)
    """
    menu = Menu(title=title, subtitle=message or "")

    menu.add_item(MenuItem("No", hotkey="N", value=False))
    menu.add_item(MenuItem("Yes", hotkey="Y", value=True))

    result = menu.run()
    if result is None:
        return False

    return result.value


