"""
Drive configuration screen - setlist toggle settings for a drive.

Allows enabling/disabling individual setlists within a chart pack.
"""

from pathlib import Path

from src.core.formatting import format_size, dedupe_files_by_newest
from src.core.constants import CHART_MARKERS
from src.config import UserSettings, extract_subfolders_from_manifest
from src.sync import get_sync_status, count_purgeable_files
from src.sync.download_planner import is_archive_file
from src.sync.state import SyncState
from src.stats import get_best_stats
from ..primitives import Colors
from ..components import format_drive_status, format_setlist_item
from ..widgets import Menu, MenuItem, MenuDivider


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


def _compute_setlist_stats_from_files(folder: dict, dedupe: bool = True) -> dict:
    """Compute setlist stats from files list."""
    stats = {}
    files = folder.get("files", [])

    if dedupe:
        files = dedupe_files_by_newest(files)

    chart_folders = {}

    for f in files:
        path = f.get("path", "")
        size = f.get("size", 0)

        if "/" not in path:
            continue

        setlist = path.split("/")[0]
        if setlist not in stats:
            stats[setlist] = {"archives": 0, "charts": 0, "total_size": 0}

        stats[setlist]["total_size"] += size

        parts = path.split("/")
        if len(parts) >= 2:
            filename = parts[-1].lower()

            if is_archive_file(filename):
                stats[setlist]["archives"] += 1
                chart_key = (setlist, path)
                chart_folders[chart_key] = {"setlist": setlist, "is_chart": True}
            elif len(parts) >= 3:
                parent = "/".join(parts[:-1])
                chart_key = (setlist, parent)
                if chart_key not in chart_folders:
                    chart_folders[chart_key] = {"setlist": setlist, "is_chart": False}
                if filename in {m.lower() for m in CHART_MARKERS}:
                    chart_folders[chart_key]["is_chart"] = True

    for key, data in chart_folders.items():
        if data["is_chart"]:
            stats[data["setlist"]]["charts"] += 1

    return stats


class DriveConfigScreen:
    """Screen for configuring setlist toggles within a drive."""

    def __init__(
        self,
        folder: dict,
        user_settings: UserSettings,
        download_path: Path = None,
        sync_state: SyncState = None,
    ):
        self.folder = folder
        self.user_settings = user_settings
        self.download_path = download_path
        self.sync_state = sync_state

    def run(self) -> str | bool:
        """Run the config screen. Returns True/False for changes, or 'scan'/'remove' for actions."""
        return show_subfolder_settings(
            self.folder,
            self.user_settings,
            self.download_path,
            self.sync_state,
        )


def show_subfolder_settings(
    folder: dict,
    user_settings: UserSettings,
    download_path: Path = None,
    sync_state: SyncState = None
) -> str | bool:
    """Show toggle menu for setlists within a drive."""
    folder_id = folder.get("folder_id", "")
    folder_name = folder.get("name", "Unknown")
    setlists = extract_subfolders_from_manifest(folder)
    is_custom = folder.get("is_custom", False)
    has_files = bool(folder.get("files"))

    if not setlists and not is_custom:
        return False

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

    computed_stats = _compute_setlist_stats_from_files(folder, dedupe=True)
    local_folder_path = download_path / folder_name if download_path else None

    if is_custom:
        setlist_stats = {name: {"archives": data["archives"], "total_size": data["total_size"]}
                        for name, data in computed_stats.items()}
    else:
        manifest_stats = {sf.get("name"): sf for sf in folder.get("subfolders", [])}
        setlist_stats = {}

        for name, data in computed_stats.items():
            computed_size = data["total_size"]
            manifest_sf = manifest_stats.get(name, {})
            manifest_charts = manifest_sf.get("charts", {}).get("total", 0)
            manifest_size = manifest_sf.get("total_size", 0)

            best_charts, best_size = get_best_stats(
                folder_name=folder_name,
                setlist_name=name,
                manifest_charts=manifest_charts,
                manifest_size=manifest_size,
                local_path=local_folder_path,
            )

            if best_size == 0 and computed_size > 0:
                best_size = computed_size

            setlist_stats[name] = {
                "charts": {"total": best_charts},
                "total_size": best_size,
            }

        for name, sf in manifest_stats.items():
            if name not in setlist_stats:
                setlist_stats[name] = sf

    changed = False
    selected_index = 0

    while True:
        drive_enabled = user_settings.is_drive_enabled(folder_id)

        # Get counts for status line
        status = get_sync_status([folder], download_path, user_settings, sync_state) if download_path else None
        excess_files, excess_size, excess_charts = count_purgeable_files([folder], download_path, user_settings, sync_state) if download_path else (0, 0, 0)

        # Count enabled setlists
        enabled_setlist_count = sum(
            1 for s in setlists
            if user_settings.is_subfolder_enabled(folder_id, s)
        )

        delta_mode = user_settings.delta_mode if user_settings else "size"

        # Build subtitle using format_drive_status
        subtitle = format_drive_status(
            synced_charts=status.synced_charts if status else 0,
            total_charts=status.total_charts if status else 0,
            enabled_setlists=enabled_setlist_count,
            total_setlists=len(setlists),
            total_size=status.total_size if status else 0,
            synced_size=status.synced_size if status else 0,
            missing_charts=status.missing_charts if status else 0,
            purgeable_files=excess_files,
            purgeable_charts=excess_charts,
            purgeable_size=excess_size,
            disabled=not drive_enabled,
            delta_mode=delta_mode,
        )

        mode_label = {"size": "Size  ", "files": "Files ", "charts": "Charts"}.get(delta_mode, "Size  ")
        legend = f"{Colors.MUTED}[Tab]{Colors.RESET} {mode_label}   {Colors.RESET}+{Colors.MUTED} add   {Colors.RED}-{Colors.MUTED} remove"
        menu = Menu(title=f"{folder_name} - Setlists:", subtitle=subtitle, space_hint="Toggle", footer=legend)

        for i, setlist_name in enumerate(setlists):
            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)

            stats = setlist_stats.get(setlist_name, {})
            total_size = stats.get("total_size", 0)

            if is_custom:
                item_count = stats.get("archives", 0)
            else:
                item_count = stats.get("charts", {}).get("total", 0)
            unit = "files" if item_count != 1 else "file"

            # Get downloaded size for this setlist
            downloaded_size = 0
            if local_folder_path:
                setlist_path = local_folder_path / setlist_name
                if setlist_path.exists():
                    downloaded_size = _get_folder_size(setlist_path)

            # Calculate purgeable for this setlist (if disabled but has content)
            # Only show deltas when drive is enabled
            setlist_purgeable_files = 0
            setlist_purgeable_size = 0
            missing_charts = 0
            is_fully_synced = downloaded_size >= total_size and total_size > 0

            if drive_enabled:
                if not setlist_enabled and downloaded_size > 0:
                    setlist_purgeable_size = downloaded_size
                    # Rough estimate: count files in the folder
                    if local_folder_path:
                        setlist_path = local_folder_path / setlist_name
                        if setlist_path.exists():
                            try:
                                setlist_purgeable_files = sum(1 for _ in setlist_path.rglob("*") if _.is_file())
                            except OSError:
                                pass

                # Calculate missing charts (only if enabled and not fully synced)
                if setlist_enabled and not is_fully_synced:
                    missing_charts = item_count

            # Format using new function
            description = format_setlist_item(
                total_charts=item_count,
                synced_charts=item_count if is_fully_synced else 0,
                total_size=total_size,
                synced_size=downloaded_size,
                purgeable_files=setlist_purgeable_files,
                purgeable_charts=item_count if setlist_purgeable_files > 0 else 0,
                purgeable_size=setlist_purgeable_size,
                missing_charts=missing_charts,
                disabled=not setlist_enabled or not drive_enabled,
                unit=unit,
                delta_mode=delta_mode,
            )

            item_disabled = not setlist_enabled or not drive_enabled
            show_toggle_colored = setlist_enabled and drive_enabled

            menu.add_item(MenuItem(setlist_name, value=("toggle", i, setlist_name), description=description if description else None, disabled=item_disabled, show_toggle=show_toggle_colored))

        menu.add_item(MenuDivider(pinned=True))

        menu.add_item(MenuItem("Enable ALL", hotkey="E", value=("enable_all", None, None), pinned=True))
        menu.add_item(MenuItem("Disable ALL", hotkey="D", value=("disable_all", None, None), pinned=True))

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

        # Handle Tab to cycle delta mode
        if result.action == "tab":
            selected_index = menu._selected
            user_settings.cycle_delta_mode()
            user_settings.save()
            continue

        action, idx, setlist_name = result.value

        if action == "enable_all":
            selected_index = menu._selected_before_hotkey
            if not user_settings.is_drive_enabled(folder_id):
                user_settings.enable_drive(folder_id)
            user_settings.enable_all(folder_id, setlists)
            user_settings.save()
            changed = True

        elif action == "disable_all":
            selected_index = menu._selected_before_hotkey
            user_settings.disable_all(folder_id, setlists)
            user_settings.save()
            changed = True

        elif action == "toggle":
            selected_index = menu._selected
            if not user_settings.is_drive_enabled(folder_id):
                # Drive is disabled - just enable it, don't toggle setlist
                user_settings.enable_drive(folder_id)
            else:
                # Drive is enabled - toggle the setlist
                user_settings.toggle_subfolder(folder_id, setlist_name)
            user_settings.save()
            changed = True

        elif action == "scan":
            return "scan"

        elif action == "remove":
            return "remove"

    return changed
