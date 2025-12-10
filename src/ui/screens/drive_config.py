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
from ..components import format_colored_size, format_sync_subtitle
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

        subtitle = ""
        if not drive_enabled:
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
                if is_custom and not status.is_actual_charts:
                    unit = "archives"
                else:
                    unit = "charts"
                subtitle = format_sync_subtitle(status, unit=unit, excess_size=excess_size)

        menu = Menu(title=f"{folder_name} - Setlists:", subtitle=subtitle, space_hint="Toggle")

        for i, setlist_name in enumerate(setlists):
            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)

            stats = setlist_stats.get(setlist_name, {})
            total_size = stats.get("total_size", 0)

            if is_custom:
                item_count = stats.get("archives", 0)
                unit = "archives" if item_count != 1 else "archive"
            else:
                item_count = stats.get("charts", {}).get("total", 0)
                unit = "charts" if item_count != 1 else "chart"

            downloaded_size = 0
            if local_folder_path:
                setlist_path = local_folder_path / setlist_name
                if setlist_path.exists():
                    downloaded_size = _get_folder_size(setlist_path)

            desc_parts = []
            if item_count:
                desc_parts.append(f"{item_count} {unit}")
            if total_size:
                desc_parts.append(format_colored_size(
                    downloaded_size, total_size,
                    synced_is_excess=(not setlist_enabled and downloaded_size > 0)
                ))
            description = ", ".join(desc_parts) if desc_parts else None

            item_disabled = not setlist_enabled or not drive_enabled
            show_toggle_colored = setlist_enabled and drive_enabled

            menu.add_item(MenuItem(setlist_name, value=("toggle", i, setlist_name), description=description, disabled=item_disabled, show_toggle=show_toggle_colored))

        menu.add_item(MenuDivider(pinned=True))

        if not drive_enabled:
            menu.add_item(MenuItem("Enable Drive", hotkey="R", value=("enable_drive", None, None), pinned=True))
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

        action, idx, setlist_name = result.value

        if action == "enable_drive":
            selected_index = menu._selected_before_hotkey
            user_settings.enable_drive(folder_id)
            user_settings.save()
            changed = True

        elif action == "enable_all":
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
            is_enabling = not user_settings.is_subfolder_enabled(folder_id, setlist_name)
            if is_enabling and not user_settings.is_drive_enabled(folder_id):
                user_settings.enable_drive(folder_id)
            user_settings.toggle_subfolder(folder_id, setlist_name)
            user_settings.save()
            changed = True

        elif action == "scan":
            return "scan"

        elif action == "remove":
            return "remove"

    return changed
