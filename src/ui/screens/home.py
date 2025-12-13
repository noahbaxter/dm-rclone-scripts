"""
Home screen - main menu of the application.

Shows available chart packs, sync status, and navigation options.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import UserSettings, DrivesConfig, extract_subfolders_from_manifest
from src.sync import get_sync_status, count_purgeable_files, SyncStatus, FolderStats, FolderStatsCache
from src.sync.state import SyncState
from ..primitives import Colors
from ..components import format_status_line, format_home_item, format_delta
from ..widgets import Menu, MenuItem, MenuDivider, MenuGroupHeader

if TYPE_CHECKING:
    from src.drive.auth import AuthManager


@dataclass
class MainMenuCache:
    """Cache for expensive main menu calculations."""
    subtitle: str = ""
    sync_action_desc: str = ""
    folder_stats: dict = field(default_factory=dict)
    group_enabled_counts: dict = field(default_factory=dict)


def _compute_folder_stats(
    folder: dict,
    download_path: Path,
    user_settings: UserSettings,
    sync_state: SyncState,
) -> FolderStats:
    """Compute stats for a single folder (sync status, purge counts, display string)."""
    folder_id = folder.get("folder_id", "")

    status = get_sync_status([folder], download_path, user_settings, sync_state)
    purge_files, purge_size, purge_charts = count_purgeable_files([folder], download_path, user_settings, sync_state)

    # Get setlist counts
    setlists = extract_subfolders_from_manifest(folder)
    total_setlists = len(setlists) if setlists else 0
    enabled_setlists = 0
    if setlists and user_settings:
        enabled_setlists = sum(
            1 for c in setlists
            if user_settings.is_subfolder_enabled(folder_id, c)
        )

    # Check if drive is enabled
    drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
    delta_mode = user_settings.delta_mode if user_settings else "size"

    # Build display string using new format
    display_string = format_home_item(
        enabled_setlists=enabled_setlists,
        total_setlists=total_setlists,
        total_size=status.total_size,
        synced_size=status.synced_size,
        purgeable_files=purge_files,
        purgeable_charts=purge_charts,
        purgeable_size=purge_size,
        missing_charts=status.missing_charts,
        disabled=not drive_enabled,
        delta_mode=delta_mode,
    )

    return FolderStats(
        folder_id=folder_id,
        sync_status=status,
        purge_count=purge_files,
        purge_charts=purge_charts,
        purge_size=purge_size,
        display_string=display_string,
    )


def compute_main_menu_cache(
    folders: list,
    user_settings: UserSettings,
    download_path: Path,
    drives_config: DrivesConfig,
    sync_state: SyncState = None,
    folder_stats_cache: FolderStatsCache = None
) -> MainMenuCache:
    """Compute all expensive stats for the main menu.

    Uses folder_stats_cache if provided to avoid recalculating unchanged folders.
    """
    cache = MainMenuCache()

    if not download_path or not folders:
        return cache

    global_status = SyncStatus()
    global_purge_count = 0
    global_purge_charts = 0
    global_purge_size = 0
    global_enabled_setlists = 0
    global_total_setlists = 0

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        is_custom = folder.get("is_custom", False)
        has_files = bool(folder.get("files"))

        if is_custom and not has_files:
            cache.folder_stats[folder_id] = "not yet scanned"
            continue

        # Try to use cached stats for this folder
        cached = folder_stats_cache.get(folder_id) if folder_stats_cache else None

        if cached:
            stats = cached
        else:
            stats = _compute_folder_stats(folder, download_path, user_settings, sync_state)
            if folder_stats_cache:
                folder_stats_cache.set(folder_id, stats)

        status = stats.sync_status
        folder_purge_count = stats.purge_count
        folder_purge_charts = stats.purge_charts
        folder_purge_size = stats.purge_size
        display_string = stats.display_string

        # Only aggregate enabled drives into global stats for add/sync
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        if drive_enabled:
            global_status.total_charts += status.total_charts
            global_status.synced_charts += status.synced_charts
            global_status.total_size += status.total_size
            global_status.synced_size += status.synced_size
            if status.is_actual_charts:
                global_status.is_actual_charts = True
        # Always aggregate purgeable (disabled drives may have content to remove)
        global_purge_count += folder_purge_count
        global_purge_charts += folder_purge_charts
        global_purge_size += folder_purge_size

        # Count setlists
        setlists = extract_subfolders_from_manifest(folder)
        if setlists:
            global_total_setlists += len(setlists)
            if user_settings:
                global_enabled_setlists += sum(
                    1 for c in setlists
                    if user_settings.is_subfolder_enabled(folder_id, c)
                )

        cache.folder_stats[folder_id] = display_string

    delta_mode = user_settings.delta_mode if user_settings else "size"

    # Build status line: 100% | 562/562 charts, 10/15 setlists (4.0 GB) [+50 charts / -80 charts]
    cache.subtitle = format_status_line(
        synced_charts=global_status.synced_charts,
        total_charts=global_status.total_charts,
        enabled_setlists=global_enabled_setlists,
        total_setlists=global_total_setlists,
        total_size=global_status.total_size,
        synced_size=global_status.synced_size,
        missing_charts=global_status.missing_charts,
        purgeable_files=global_purge_count,
        purgeable_charts=global_purge_charts,
        purgeable_size=global_purge_size,
        delta_mode=delta_mode,
    )

    # Build sync action description: [+2.6 MB / -317.3 MB] or [+50 files / -80 files]
    cache.sync_action_desc = format_delta(
        add_size=global_status.missing_size,
        add_files=global_status.missing_charts,  # Use chart count for files (best we have)
        add_charts=global_status.missing_charts,
        remove_size=global_purge_size,
        remove_files=global_purge_count,
        remove_charts=global_purge_charts,
        mode=delta_mode,
        empty_text="Everything in sync",
    )

    if drives_config:
        for group_name in drives_config.get_groups():
            group_drives = drives_config.get_drives_in_group(group_name)
            enabled_count = sum(
                1 for d in group_drives
                if (user_settings.is_drive_enabled(d.folder_id) if user_settings else True)
            )
            cache.group_enabled_counts[group_name] = enabled_count

    return cache


class HomeScreen:
    """Main menu screen showing available chart packs."""

    def __init__(
        self,
        folders: list,
        user_settings: UserSettings = None,
        download_path: Path = None,
        drives_config: DrivesConfig = None,
        auth: "AuthManager" = None,
        sync_state: SyncState = None,
    ):
        self.folders = folders
        self.user_settings = user_settings
        self.download_path = download_path
        self.drives_config = drives_config
        self.auth = auth
        self.sync_state = sync_state
        self._cache = None
        self._selected_index = 0

    def run(self) -> tuple[str, str | int | None, int]:
        """Run the home screen. Returns (action, value, menu_position)."""
        return show_main_menu(
            self.folders,
            self.user_settings,
            self._selected_index,
            self.download_path,
            self.drives_config,
            self._cache,
            self.auth,
            self.sync_state,
        )


def show_main_menu(
    folders: list,
    user_settings: UserSettings = None,
    selected_index: int = 0,
    download_path: Path = None,
    drives_config: DrivesConfig = None,
    cache: MainMenuCache = None,
    auth=None,
    sync_state: SyncState = None
) -> tuple[str, str | int | None, int]:
    """
    Show main menu and get user selection.

    Returns tuple of (action, value, menu_position).
    """
    if cache is None:
        cache = compute_main_menu_cache(folders, user_settings, download_path, drives_config, sync_state)

    delta_mode = user_settings.delta_mode if user_settings else "size"
    mode_label = {"size": "Size  ", "files": "Files ", "charts": "Charts"}.get(delta_mode, "Size  ")
    legend = f"{Colors.MUTED}[Tab]{Colors.RESET} {mode_label}   {Colors.RESET}+{Colors.MUTED} add   {Colors.RED}-{Colors.MUTED} remove"
    menu = Menu(title="Available chart packs:", subtitle=cache.subtitle, space_hint="Toggle", footer=legend, esc_label="Quit")

    folder_lookup = {f.get("folder_id", ""): f for f in folders}

    grouped_folder_ids = set()
    groups = []
    if drives_config:
        groups = drives_config.get_groups()
        for drive in drives_config.drives:
            if drive.group:
                grouped_folder_ids.add(drive.folder_id)

    added_folders = set()
    hotkey_num = 1

    def add_folder_item(folder: dict, indent: bool = False):
        nonlocal hotkey_num
        folder_id = folder.get("folder_id", "")
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        stats = cache.folder_stats.get(folder_id)

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

    if drives_config:
        for drive in drives_config.get_ungrouped_drives():
            folder = folder_lookup.get(drive.folder_id)
            if folder:
                add_folder_item(folder)

    for group_name in groups:
        expanded = user_settings.is_group_expanded(group_name) if user_settings else False

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
            added_folders.add(drive.folder_id)
            if expanded:
                folder = folder_lookup.get(drive.folder_id)
                if folder:
                    add_folder_item(folder, indent=True)

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        if folder_id not in added_folders:
            add_folder_item(folder)

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Sync", hotkey="S", value=("sync", None), description=cache.sync_action_desc))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Add Custom Folder", hotkey="A", value=("add_custom", None), description="Add your own Google Drive folder"))

    if auth and auth.is_signed_in:
        email = auth.user_email
        label = f"Sign out ({email})" if email else "Sign out of Google"
        menu.add_item(MenuItem(label, hotkey="G", value=("signout", None), description="Remove saved Google credentials"))
    else:
        menu.add_item(MenuItem("Sign in to Google", hotkey="G", value=("signin", None), description="Faster downloads with your own quota"))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Quit", value=("quit", None)))

    result = menu.run(initial_index=selected_index)
    if result is None:
        return ("quit", None, selected_index)

    # Handle Tab to cycle delta mode
    if result.action == "tab":
        return ("cycle_delta_mode", None, menu._selected)

    restore_pos = menu._selected_before_hotkey if menu._selected_before_hotkey != menu._selected else menu._selected

    if isinstance(result.value, tuple) and len(result.value) == 2 and result.value[0] == "group":
        return ("toggle_group", result.value[1], menu._selected)

    if isinstance(result.value, str) and not result.value.startswith(("download", "purge", "quit")):
        if result.action == "space":
            return ("toggle", result.value, menu._selected)
        else:
            return ("configure", result.value, menu._selected)

    action, value = result.value
    return (action, value, restore_pos)
