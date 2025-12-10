"""
User interface components for DM Chart Sync.

Handles menu display, user input, and terminal operations.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core.formatting import format_size, dedupe_files_by_newest
from .terminal import clear_screen
from ..config import UserSettings, DrivesConfig, extract_subfolders_from_manifest
from ..sync import get_sync_status, count_purgeable_files, SyncStatus
from ..sync.state import SyncState
from ..stats import get_best_stats, get_scanner, get_overrides
from .menu import Menu, MenuItem, MenuDivider, MenuGroupHeader, MenuResult, print_header
from .colors import Colors


def format_colored_count(
    synced: int,
    total: int,
    excess: int = 0,
    synced_is_excess: bool = False
) -> str:
    """
    Format a colored count display.

    Args:
        synced: Number of synced items
        total: Total number of items
        excess: Number of excess items (shown in red prefix)
        synced_is_excess: If True, show synced in red (for disabled items with content)

    Returns:
        Formatted string like "20 + 108/108" with colors (caller adds unit if needed)
        Or just "45" in red if total is 0 but excess > 0
    """
    m = Colors.MUTED

    if excess > 0:
        if total == 0:
            # Everything is purgeable, just show excess in red
            return f"{Colors.RED}{excess}"
        return f"{Colors.RED}{excess}{m} + {Colors.RESET}{synced}{m}/{total}"
    elif synced_is_excess and synced > 0:
        return f"{Colors.RED}{synced}{m}/{total}"
    elif synced > 0:
        return f"{Colors.RESET}{synced}{m}/{total}"
    else:
        return f"{synced}/{total}"


def format_colored_size(
    synced_size: int,
    total_size: int,
    excess_size: int = 0,
    synced_is_excess: bool = False
) -> str:
    """
    Format a colored size display.

    Args:
        synced_size: Size of synced data
        total_size: Total size
        excess_size: Size of excess data (shown in red prefix)
        synced_is_excess: If True, show synced_size in red (for disabled items with content)

    Returns:
        Formatted string like "1.6 GB + 4.2 GB/4.2 GB" with colors
        Or just "1.5 GB" in red if total_size is 0 but excess_size > 0
    """
    m = Colors.MUTED

    if excess_size > 0:
        if total_size == 0:
            # Everything is purgeable, just show excess in red
            return f"{Colors.RED}{format_size(excess_size)}"
        return f"{Colors.RED}{format_size(excess_size)}{m} + {Colors.RESET}{format_size(synced_size)}{m}/{format_size(total_size)}"
    elif synced_is_excess and synced_size > 0:
        # Use synced as total if total is 0 (missing manifest data)
        effective_total = total_size if total_size > 0 else synced_size
        return f"{Colors.RED}{format_size(synced_size)}{m}/{format_size(effective_total)}"
    elif synced_size > 0:
        # Use synced as total if total is 0 (missing manifest data)
        effective_total = total_size if total_size > 0 else synced_size
        return f"{Colors.RESET}{format_size(synced_size)}{m}/{format_size(effective_total)}"
    else:
        return format_size(total_size)


def format_sync_subtitle(
    status: SyncStatus,
    unit: str = "charts",
    excess_size: int = 0
) -> str:
    """
    Format a sync status subtitle line.

    Args:
        status: SyncStatus with chart/archive counts
        unit: "charts" or "archives"
        excess_size: Size of excess data (purgeable, shown in red)

    Returns:
        Formatted string like "Synced: 108/108 charts (4.2 GB + 1.6 GB/4.2 GB) | 100%"
        Or if everything is purgeable: "Purgeable: 1.5 GB"
    """
    # If no enabled content but have excess, show purgeable-only format
    if status.total_charts == 0:
        if excess_size > 0:
            return f"Purgeable: {Colors.RED}{format_size(excess_size)}{Colors.MUTED}"
        return ""

    pct = (status.synced_charts / status.total_charts * 100)
    charts_str = format_colored_count(status.synced_charts, status.total_charts)

    # If total_size is 0 but we have synced data, use synced_size as total
    # (handles manifests with missing size data, like Guitar Hero archives)
    effective_total_size = status.total_size if status.total_size > 0 else status.synced_size
    size_str = format_colored_size(status.synced_size, effective_total_size, excess_size=excess_size)

    return f"Synced: {charts_str} {unit} ({size_str}) | {pct:.0f}%"


def _get_folder_size(folder_path: Path) -> int:
    """Get total size of all files in a folder recursively."""
    if not folder_path.exists():
        return 0
    total = 0
    try:
        for item in folder_path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


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
    drives_config: DrivesConfig,
    sync_state: SyncState = None
) -> MainMenuCache:
    """
    Compute all expensive stats for the main menu.

    Call this once, then reuse for group expand/collapse operations.
    """
    cache = MainMenuCache()

    if not download_path or not folders:
        return cache

    # Accumulate global stats from per-folder stats (avoids N+1 scanning)
    global_status = SyncStatus()
    global_purge_count = 0
    global_purge_size = 0

    cache_start = time.time()

    # Calculate per-folder stats in a single pass
    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        stats_parts = []

        # Check if this is a custom folder that hasn't been scanned yet
        is_custom = folder.get("is_custom", False)
        has_files = bool(folder.get("files"))

        if is_custom and not has_files:
            # Custom folder not yet scanned
            cache.folder_stats[folder_id] = "not yet scanned"
            continue

        folder_start = time.time()

        # Get sync status for this folder (enabled only)
        status = get_sync_status([folder], download_path, user_settings, sync_state)

        # Get excess/purgeable count for this folder
        folder_purge_count, folder_purge_size = count_purgeable_files([folder], download_path, user_settings, sync_state)

        folder_time = time.time() - folder_start
        if folder_time > 1.0:  # Only log if > 1 second
            print(f"  [perf] {folder_name}: {folder_time:.1f}s")

        # Accumulate into global totals
        global_status.total_charts += status.total_charts
        global_status.synced_charts += status.synced_charts
        global_status.total_size += status.total_size
        global_status.synced_size += status.synced_size
        if status.is_actual_charts:
            global_status.is_actual_charts = True
        global_purge_count += folder_purge_count
        global_purge_size += folder_purge_size

        # Show charts with excess prefix if applicable
        # Use "archives" for custom folders before extraction, "charts" after we've scanned actual content
        if status.total_charts or folder_purge_count:
            if is_custom and not status.is_actual_charts:
                unit = "archives"
            else:
                unit = "charts"

            stats_parts.append(f"{format_colored_count(status.synced_charts, status.total_charts, excess=folder_purge_count)} {unit}")

        setlists = extract_subfolders_from_manifest(folder)
        if setlists and user_settings:
            enabled_setlists = [
                c for c in setlists
                if user_settings.is_subfolder_enabled(folder_id, c)
            ]
            stats_parts.append(f"{len(enabled_setlists)}/{len(setlists)} setlists")

        stats_parts.append(format_colored_size(status.synced_size, status.total_size, excess_size=folder_purge_size))

        cache.folder_stats[folder_id] = ", ".join(stats_parts) if stats_parts else None

    # Format global subtitle with accumulated stats
    cache.subtitle = format_sync_subtitle(
        global_status,
        unit="charts",
        excess_size=global_purge_size
    )

    if global_purge_count > 0:
        cache.purge_desc = f"{Colors.RED}{global_purge_count} files, {format_size(global_purge_size)}{Colors.MUTED}"

    # Calculate group enabled counts
    if drives_config:
        for group_name in drives_config.get_groups():
            group_drives = drives_config.get_drives_in_group(group_name)
            enabled_count = sum(
                1 for d in group_drives
                if (user_settings.is_drive_enabled(d.folder_id) if user_settings else True)
            )
            cache.group_enabled_counts[group_name] = enabled_count

    total_time = time.time() - cache_start
    if total_time > 2.0:  # Only log if > 2 seconds
        print(f"  [perf] Menu cache computed in {total_time:.1f}s")

    return cache


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

    Args:
        folders: List of folder dicts from manifest
        user_settings: User settings for checking charter enabled states
        selected_index: Index to keep selected (for maintaining position after toggle)
        download_path: Path to download folder for sync status calculation
        drives_config: Drive configuration with group information
        cache: Pre-computed stats cache (if None, will compute fresh)
        auth: AuthManager instance for checking sign-in state

    Returns tuple of (action, value, menu_position):
        - ("quit", None, pos) - user wants to quit
        - ("download", None, pos) - download all enabled
        - ("purge", None, pos) - purge extra files
        - ("configure", folder_id, pos) - configure specific drive (enter on drive)
        - ("toggle", folder_id, pos) - toggle drive on/off (space on drive)
        - ("toggle_group", group_name, pos) - expand/collapse group
        - ("signin", None, pos) - sign in to Google
        - ("signout", None, pos) - sign out of Google
    """
    # Compute cache if not provided
    if cache is None:
        cache = compute_main_menu_cache(folders, user_settings, download_path, drives_config, sync_state)

    # Build footer with color legend
    legend = f"{Colors.RESET}White{Colors.MUTED} = synced   {Colors.RED}Red{Colors.MUTED} = purgeable"
    menu = Menu(title="Available chart packs:", subtitle=cache.subtitle, space_hint="Toggle", footer=legend, esc_label="Quit")

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
    menu.add_item(MenuItem("Sync", hotkey="S", value=("sync", None), description="Download missing, purge extras"))

    # Custom folders option
    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Add Custom Folder", hotkey="A", value=("add_custom", None), description="Add your own Google Drive folder"))

    # Google sign-in/sign-out option
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


def _compute_setlist_stats_from_files(folder: dict, dedupe: bool = True) -> dict:
    """
    Compute setlist stats from files list.

    Args:
        folder: Folder dict with "files" list
        dedupe: If True, deduplicate files first (removes older versions with same path)

    Returns dict mapping setlist name to {archives: int, charts: int, total_size: int}
    """
    from ..sync.download_planner import is_archive_file
    from ..core.constants import CHART_MARKERS

    stats = {}
    files = folder.get("files", [])

    if dedupe:
        files = dedupe_files_by_newest(files)

    # Group files by chart folder to count charts properly
    chart_folders = {}  # (setlist, path) -> {setlist, is_chart}

    for f in files:
        path = f.get("path", "")
        size = f.get("size", 0)

        if "/" not in path:
            continue

        setlist = path.split("/")[0]
        if setlist not in stats:
            stats[setlist] = {"archives": 0, "charts": 0, "total_size": 0}

        stats[setlist]["total_size"] += size

        # Determine parent folder (chart folder)
        parts = path.split("/")
        if len(parts) >= 2:
            # For archives at setlist/archive.zip level, parent is setlist
            # For files at setlist/chart/file level, parent is setlist/chart
            filename = parts[-1].lower()

            if is_archive_file(filename):
                stats[setlist]["archives"] += 1
                # Each archive is a chart
                chart_key = (setlist, path)  # Unique per archive
                chart_folders[chart_key] = {"setlist": setlist, "is_chart": True}
            elif len(parts) >= 3:
                # Regular file in a chart folder
                parent = "/".join(parts[:-1])
                chart_key = (setlist, parent)
                if chart_key not in chart_folders:
                    chart_folders[chart_key] = {"setlist": setlist, "is_chart": False}
                # Check for chart markers
                if filename in {m.lower() for m in CHART_MARKERS}:
                    chart_folders[chart_key]["is_chart"] = True

    # Count charts per setlist
    for key, data in chart_folders.items():
        if data["is_chart"]:
            stats[data["setlist"]]["charts"] += 1

    return stats


def show_subfolder_settings(folder: dict, user_settings: UserSettings, download_path: Path = None, sync_state: SyncState = None) -> str | bool:
    """
    Show toggle menu for setlists within a drive.

    Args:
        folder: Folder dict from manifest
        user_settings: User settings to read/write toggle states
        download_path: Path to download folder for sync status calculation

    Returns:
        - True if settings were changed
        - False if no changes
        - "scan" if user requested to scan custom folder
        - "remove" if user requested to remove custom folder
    """
    folder_id = folder.get("folder_id", "")
    folder_name = folder.get("name", "Unknown")
    setlists = extract_subfolders_from_manifest(folder)
    is_custom = folder.get("is_custom", False)
    has_files = bool(folder.get("files"))

    # For non-custom folders with no setlists, nothing to show
    if not setlists and not is_custom:
        return False

    # For custom folders with no setlists, show scan/remove options only
    if not setlists and is_custom:
        menu = Menu(title=f"{folder_name}:", subtitle="Folder not yet scanned")
        scan_label = "Re-scan folder" if has_files else "Scan folder"
        scan_desc = "Refresh file list from Google Drive" if has_files else "Get file list from Google Drive"
        menu.add_item(MenuItem(scan_label, hotkey="S", value="scan", description=scan_desc))
        menu.add_item(MenuItem("Remove folder", hotkey="X", value="remove", description="Remove from custom folders"))
        menu.add_item(MenuDivider())
        menu.add_item(MenuItem("Back", value="back"))

        result = menu.run()
        if result and result.value in ("scan", "remove"):
            return result.value
        return False

    # Build lookup for setlist stats
    # For custom folders, use archive count from computed stats
    # For regular drives, use get_best_stats() which checks: local scan > overrides > manifest
    computed_stats = _compute_setlist_stats_from_files(folder, dedupe=True)
    local_folder_path = download_path / folder_name if download_path else None

    if is_custom:
        # Custom folders use archive count
        setlist_stats = {name: {"archives": data["archives"], "total_size": data["total_size"]}
                        for name, data in computed_stats.items()}
    else:
        # Regular drives: use the new stats module for best available data
        # Priority: local disk scan > admin overrides > manifest data
        manifest_stats = {sf.get("name"): sf for sf in folder.get("subfolders", [])}
        setlist_stats = {}

        for name, data in computed_stats.items():
            computed_size = data["total_size"]

            # Get manifest stats for this setlist
            manifest_sf = manifest_stats.get(name, {})
            manifest_charts = manifest_sf.get("charts", {}).get("total", 0)
            manifest_size = manifest_sf.get("total_size", 0)

            # Use get_best_stats() for smart resolution
            best_charts, best_size = get_best_stats(
                folder_name=folder_name,
                setlist_name=name,
                manifest_charts=manifest_charts,
                manifest_size=manifest_size,
                local_path=local_folder_path,
            )

            # If best_size is 0 but we have computed size, use that
            if best_size == 0 and computed_size > 0:
                best_size = computed_size

            setlist_stats[name] = {
                "charts": {"total": best_charts},
                "total_size": best_size,
            }

        # Include any setlists from manifest that weren't in computed (shouldn't happen, but safe)
        for name, sf in manifest_stats.items():
            if name not in setlist_stats:
                setlist_stats[name] = sf

    changed = False
    selected_index = 0  # Track menu position to maintain after any action

    while True:
        # Check if drive is enabled
        drive_enabled = user_settings.is_drive_enabled(folder_id)

        # Calculate sync status for just this drive
        subtitle = ""
        if not drive_enabled:
            # Drive is disabled - check for purgeable content
            if download_path:
                excess_charts, excess_size = count_purgeable_files([folder], download_path, user_settings, sync_state)
                if excess_charts > 0:
                    subtitle = f"DRIVE DISABLED - {Colors.RED}Purgeable: {excess_charts} files ({format_size(excess_size)}){Colors.RESET}"
                else:
                    subtitle = "DRIVE DISABLED"
            else:
                subtitle = "DRIVE DISABLED"
        elif download_path:
            status = get_sync_status([folder], download_path, user_settings, sync_state)
            excess_charts, excess_size = count_purgeable_files([folder], download_path, user_settings, sync_state)

            if status.total_charts > 0 or excess_charts > 0:
                # Use "archives" for custom folders before extraction, "charts" after
                if is_custom and not status.is_actual_charts:
                    unit = "archives"
                else:
                    unit = "charts"
                subtitle = format_sync_subtitle(
                    status,
                    unit=unit,
                    excess_size=excess_size
                )

        menu = Menu(title=f"{folder_name} - Setlists:", subtitle=subtitle, space_hint="Toggle")

        # Add setlist toggle items (no hotkeys - too many setlists)
        for i, setlist_name in enumerate(setlists):
            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)

            # Get setlist stats
            stats = setlist_stats.get(setlist_name, {})
            total_size = stats.get("total_size", 0)

            # For custom folders, use archive count; for regular drives, use chart count
            if is_custom:
                item_count = stats.get("archives", 0)
                unit = "archives" if item_count != 1 else "archive"
            else:
                item_count = stats.get("charts", {}).get("total", 0)
                unit = "charts" if item_count != 1 else "chart"

            # Check downloaded size for this setlist
            downloaded_size = 0
            if local_folder_path:
                setlist_path = local_folder_path / setlist_name
                if setlist_path.exists():
                    downloaded_size = _get_folder_size(setlist_path)

            # Build description with color-coded sizes
            desc_parts = []
            if item_count:
                desc_parts.append(f"{item_count} {unit}")
            if total_size:
                # synced_is_excess=True when setlist is OFF but has downloaded content (purgeable)
                desc_parts.append(format_colored_size(
                    downloaded_size, total_size,
                    synced_is_excess=(not setlist_enabled and downloaded_size > 0)
                ))
            description = ", ".join(desc_parts) if desc_parts else None

            # If drive is disabled, all items appear disabled (greyed out)
            # show_toggle only shows colored [ON] when drive is also enabled
            item_disabled = not setlist_enabled or not drive_enabled
            show_toggle_colored = setlist_enabled and drive_enabled

            menu.add_item(MenuItem(setlist_name, value=("toggle", i, setlist_name), description=description, disabled=item_disabled, show_toggle=show_toggle_colored))

        # Pinned items at bottom (always visible, not scrolled)
        menu.add_item(MenuDivider(pinned=True))

        # Show Enable Drive option if drive is disabled
        if not drive_enabled:
            menu.add_item(MenuItem("Enable Drive", hotkey="R", value=("enable_drive", None, None), pinned=True))
            menu.add_item(MenuDivider(pinned=True))

        menu.add_item(MenuItem("Enable ALL", hotkey="E", value=("enable_all", None, None), pinned=True))
        menu.add_item(MenuItem("Disable ALL", hotkey="D", value=("disable_all", None, None), pinned=True))

        # Custom folder options
        if is_custom:
            menu.add_item(MenuDivider(pinned=True))
            has_files = bool(folder.get("files"))
            scan_label = "Re-scan folder" if has_files else "Scan folder"
            scan_desc = "Refresh file list from Google Drive" if has_files else "Get file list from Google Drive"
            menu.add_item(MenuItem(scan_label, hotkey="S", value=("scan", None, None), description=scan_desc, pinned=True))
            menu.add_item(MenuItem("Remove folder", hotkey="X", value=("remove", None, None), description="Remove from custom folders", pinned=True))

        menu.add_item(MenuDivider(pinned=True))
        menu.add_item(MenuItem("Back", value=("back", None, None), pinned=True))

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
            # Also enable the drive if it's currently disabled
            if not user_settings.is_drive_enabled(folder_id):
                user_settings.enable_drive(folder_id)
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
            # If enabling a setlist on a disabled drive, also enable the drive
            is_enabling = not user_settings.is_subfolder_enabled(folder_id, setlist_name)
            if is_enabling and not user_settings.is_drive_enabled(folder_id):
                user_settings.enable_drive(folder_id)
            user_settings.toggle_subfolder(folder_id, setlist_name)
            user_settings.save()
            changed = True

        elif action == "scan":
            # Return special action for custom folder scan
            return "scan"

        elif action == "remove":
            # Return special action for custom folder removal
            return "remove"

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


def show_oauth_prompt() -> bool:
    """
    Show first-run OAuth sign-in prompt.

    Explains the benefit of signing in (faster downloads, own quota)
    and lets user choose to sign in or skip.

    Returns:
        True if user wants to sign in, False to skip
    """
    from .keyboard import getch

    clear_screen()
    print_header()
    print()
    print("  Sign in to Google for faster downloads?")
    print()
    print("  Signing in gives you your own download quota,")
    print("  which means fewer rate limits and faster syncs.")
    print()
    print("  Your Google account is only used to download files.")
    print("  We never upload, modify, or access anything else.")
    print()
    print("  [Y] Sign in (recommended)")
    print("  [N] Skip for now")
    print()

    while True:
        key = getch().lower()
        if key == "y":
            return True
        elif key == "n" or key == "\x1b":  # N or ESC
            return False


def show_add_custom_folder(client, auth=None) -> tuple[str | None, str | None]:
    """
    Show the Add Custom Folder screen.

    Prompts user for Google Drive folder URL/ID, validates it,
    and returns the folder info.

    Args:
        client: DriveClient instance with user's OAuth token
        auth: AuthManager instance (reserved for future use)

    Returns:
        Tuple of (folder_id, folder_name) if successful, (None, None) if cancelled
    """
    from .keyboard import input_with_esc, CancelInput, wait_with_skip
    from ..drive.utils import parse_drive_folder_url
    from .colors import Colors

    clear_screen()
    print_header()
    print()
    print("  Add Custom Folder")
    print()
    print("  Paste a Google Drive folder URL or ID.")
    print("  The folder must be shared (anyone with link) or in your Drive.")
    print()
    print("  Example: https://drive.google.com/drive/folders/abc123...")
    print()
    print(f"  {Colors.DIM}Press ESC to cancel{Colors.RESET}")
    print()

    try:
        url_input = input_with_esc("  URL or ID: ")
    except CancelInput:
        return None, None

    if not url_input.strip():
        print("\n  No URL entered.")
        wait_with_skip(2)
        return None, None

    # Parse the URL/ID
    folder_id, error = parse_drive_folder_url(url_input)
    if not folder_id:
        print(f"\n  {Colors.BOLD}{error}{Colors.RESET}")
        print("  Please use a Google Drive folder link like:")
        print("  https://drive.google.com/drive/folders/abc123...")
        wait_with_skip(3)
        return None, None

    # Validate the folder
    print("\n  Checking folder access...")

    is_valid, folder_name = client.validate_folder(folder_id)

    if not is_valid:
        print(f"\n  {Colors.BOLD}Could not access folder.{Colors.RESET}")
        print("  Make sure the folder is shared or you have access.")
        wait_with_skip(3)
        return None, None

    print(f"  Found: {Colors.BOLD}{folder_name}{Colors.RESET}")
    wait_with_skip(1)

    return folder_id, folder_name


