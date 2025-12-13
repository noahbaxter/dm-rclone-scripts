"""
Home screen - main menu of the application.

Shows available chart packs, sync status, and navigation options.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.formatting import format_size
from src.config import UserSettings, DrivesConfig, extract_subfolders_from_manifest
from src.sync import get_sync_status, count_purgeable_files, SyncStatus, FolderStats, FolderStatsCache
from src.sync.state import SyncState
from ..primitives import Colors
from ..components import format_colored_count, format_colored_size, format_sync_subtitle
from ..widgets import Menu, MenuItem, MenuDivider, MenuGroupHeader

if TYPE_CHECKING:
    from src.drive.auth import AuthManager


@dataclass
class MainMenuCache:
    """Cache for expensive main menu calculations."""
    subtitle: str = ""
    purge_desc: str | None = None
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
    is_custom = folder.get("is_custom", False)

    status = get_sync_status([folder], download_path, user_settings, sync_state)
    purge_count, purge_size = count_purgeable_files([folder], download_path, user_settings, sync_state)

    # Build display string
    stats_parts = []
    if status.total_charts or purge_count:
        if is_custom and not status.is_actual_charts:
            unit = "archives"
        else:
            unit = "charts"
        stats_parts.append(f"{format_colored_count(status.synced_charts, status.total_charts, excess=purge_count)} {unit}")

    setlists = extract_subfolders_from_manifest(folder)
    if setlists and user_settings:
        enabled_setlists = [
            c for c in setlists
            if user_settings.is_subfolder_enabled(folder_id, c)
        ]
        stats_parts.append(f"{len(enabled_setlists)}/{len(setlists)} setlists")

    stats_parts.append(format_colored_size(status.synced_size, status.total_size, excess_size=purge_size))

    display_string = ", ".join(stats_parts) if stats_parts else None

    return FolderStats(
        folder_id=folder_id,
        sync_status=status,
        purge_count=purge_count,
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
    global_purge_size = 0

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
        folder_purge_size = stats.purge_size
        display_string = stats.display_string

        # Aggregate into global stats
        global_status.total_charts += status.total_charts
        global_status.synced_charts += status.synced_charts
        global_status.total_size += status.total_size
        global_status.synced_size += status.synced_size
        if status.is_actual_charts:
            global_status.is_actual_charts = True
        global_purge_count += folder_purge_count
        global_purge_size += folder_purge_size

        cache.folder_stats[folder_id] = display_string

    cache.subtitle = format_sync_subtitle(
        global_status,
        unit="charts",
        excess_size=global_purge_size
    )

    if global_purge_count > 0:
        cache.purge_desc = f"{Colors.RED}{global_purge_count} files, {format_size(global_purge_size)}{Colors.MUTED}"

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

    legend = f"{Colors.RESET}White{Colors.MUTED} = synced   {Colors.RED}Red{Colors.MUTED} = purgeable"
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
    menu.add_item(MenuItem("Sync", hotkey="S", value=("sync", None), description="Download missing, purge extras"))

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
