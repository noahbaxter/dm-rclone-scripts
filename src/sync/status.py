"""
Sync status calculation for DM Chart Sync.

Determines what's synced by comparing local files against manifest.
"""

import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..core.constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS
from ..core.formatting import sanitize_path, dedupe_files_by_newest
from ..stats import get_best_stats
from .cache import scan_local_files, scan_actual_charts
from .state import SyncState


@dataclass
class SyncStatus:
    """Status of local charts vs manifest."""
    total_charts: int = 0
    synced_charts: int = 0
    total_size: int = 0
    synced_size: int = 0
    # True if counts are from actual folder scan (real charts)
    # False if counts are from manifest (archives, not yet extracted)
    is_actual_charts: bool = False

    @property
    def missing_charts(self) -> int:
        return self.total_charts - self.synced_charts

    @property
    def missing_size(self) -> int:
        return self.total_size - self.synced_size

    @property
    def is_synced(self) -> bool:
        return self.synced_charts == self.total_charts


def is_archive_file(filename: str) -> bool:
    """Check if a filename is an archive type we handle."""
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


def _check_archive_synced(
    sync_state: SyncState,
    folder_name: str,
    checksum_path: str,
    archive_name: str,
    manifest_md5: str,
) -> tuple[bool, int]:
    """
    Check if an archive is synced using sync_state.

    Args:
        sync_state: SyncState instance (can be None)
        folder_name: Folder name (e.g., "Guitar Hero")
        checksum_path: Parent path within folder (e.g., "(2005) Guitar Hero")
        archive_name: Archive filename (e.g., "Guitar Hero.7z")
        manifest_md5: Expected MD5 from manifest

    Returns:
        Tuple of (is_synced, extracted_size)
    """
    if not sync_state:
        return False, 0

    # Build full archive path: folder_name/checksum_path/archive_name
    if checksum_path:
        archive_path = f"{folder_name}/{checksum_path}/{archive_name}"
    else:
        archive_path = f"{folder_name}/{archive_name}"

    if sync_state.is_archive_synced(archive_path, manifest_md5):
        # Verify extracted files still exist on disk
        archive_files = sync_state.get_archive_files(archive_path)
        missing = sync_state.check_files_exist(archive_files)
        if len(missing) == 0:
            # Get size from archive node
            archive = sync_state.get_archive(archive_path)
            extracted_size = archive.get("archive_size", 0) if archive else 0
            return True, extracted_size

    return False, 0


def get_sync_status(folders: list, base_path: Path, user_settings=None, sync_state: SyncState = None) -> SyncStatus:
    """
    Calculate sync status for enabled folders (counts charts, not files).

    Args:
        folders: List of folder dicts from manifest
        base_path: Base download path
        user_settings: UserSettings for checking enabled states
        sync_state: SyncState for checking synced archives (optional, falls back to check.txt)

    Returns:
        SyncStatus with chart totals and synced counts
    """
    status = SyncStatus()

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name
        is_custom = folder.get("is_custom", False)

        # Skip disabled drives
        if user_settings and not user_settings.is_drive_enabled(folder_id):
            continue

        manifest_files = folder.get("files", [])
        if not manifest_files:
            continue

        # Deduplicate files with same path, keeping only newest version
        manifest_files = dedupe_files_by_newest(manifest_files)

        # Get disabled setlists (needed for both custom and regular folders)
        disabled_setlists = set()
        if user_settings:
            disabled_setlists = user_settings.get_disabled_subfolders(folder_id)

        # For custom folders, we need both:
        # - Totals: disk size for downloaded setlists, manifest size for not-downloaded
        # - Synced: disk size for downloaded setlists
        synced_from_scan = None
        downloaded_setlist_sizes = {}  # setlist_name -> actual disk size
        if is_custom and folder_path.exists():
            actual_charts, actual_size = scan_actual_charts(folder_path, disabled_setlists)
            if actual_charts > 0:
                synced_from_scan = (actual_charts, actual_size)
                status.is_actual_charts = True
                # Track per-setlist disk sizes for downloaded setlists
                try:
                    for entry in os.scandir(folder_path):
                        if entry.is_dir() and not entry.name.startswith('.'):
                            setlist_name = entry.name
                            if disabled_setlists and setlist_name in disabled_setlists:
                                continue
                            # Get actual size on disk for this setlist
                            setlist_charts, setlist_size = scan_actual_charts(Path(entry.path), set())
                            if setlist_charts > 0:
                                downloaded_setlist_sizes[setlist_name] = setlist_size
                except OSError:
                    pass

        # Group files by parent folder to identify charts
        # chart_folders: {parent_path: {files: [...], is_chart: bool, total_size: int, archive_md5: str, archive_name: str, checksum_path: str}}
        chart_folders = defaultdict(lambda: {"files": [], "is_chart": False, "total_size": 0, "archive_md5": "", "archive_name": "", "checksum_path": ""})

        for f in manifest_files:
            file_path = f.get("path", "")
            file_size = f.get("size", 0)
            file_md5 = f.get("md5", "")

            # Sanitize path for cross-platform compatibility (must match download logic)
            sanitized_path = sanitize_path(file_path)

            # Split path into parent folder and filename
            slash_idx = sanitized_path.rfind("/")
            if slash_idx == -1:
                # Root-level file
                file_name = sanitized_path.lower()
                archive_name = sanitized_path  # Full filename for lookup

                # Root-level archives are each treated as individual charts
                if is_archive_file(file_name):
                    # Use the archive path itself as the "parent" key (unique per archive)
                    chart_folders[sanitized_path]["files"].append((sanitized_path, file_size))
                    chart_folders[sanitized_path]["total_size"] += file_size
                    chart_folders[sanitized_path]["is_chart"] = True
                    chart_folders[sanitized_path]["archive_md5"] = file_md5
                    chart_folders[sanitized_path]["archive_name"] = archive_name
                    chart_folders[sanitized_path]["checksum_path"] = ""  # Root folder
                # Skip other root-level files (non-archives)
                continue

            parent = sanitized_path[:slash_idx]
            file_name = sanitized_path[slash_idx + 1:].lower()
            archive_name = sanitized_path[slash_idx + 1:]  # Full filename for lookup

            # Skip files in disabled setlists (only check if has subfolders)
            if disabled_setlists:
                first_slash = file_path.find("/")
                setlist = file_path[:first_slash] if first_slash != -1 else file_path
                if setlist in disabled_setlists:
                    continue

            # Archives are each treated as individual charts (one archive = one song)
            # Use full path as key so each archive counts separately
            if is_archive_file(file_name):
                chart_folders[sanitized_path]["files"].append((sanitized_path, file_size))
                chart_folders[sanitized_path]["total_size"] += file_size
                chart_folders[sanitized_path]["is_chart"] = True
                chart_folders[sanitized_path]["archive_md5"] = file_md5
                chart_folders[sanitized_path]["archive_name"] = archive_name
                chart_folders[sanitized_path]["checksum_path"] = parent
            else:
                # Non-archive files: group by parent folder
                chart_folders[parent]["files"].append((sanitized_path, file_size))
                chart_folders[parent]["total_size"] += file_size

                # Check for chart markers (song.ini, notes.mid, etc.)
                if file_name in CHART_MARKERS:
                    chart_folders[parent]["is_chart"] = True

        # Batch scan: get all local files upfront
        local_files = scan_local_files(folder_path)

        # For custom folders, track manifest sizes per setlist so we can replace with disk sizes
        setlist_manifest_sizes = {}  # setlist_name -> manifest size
        if is_custom and downloaded_setlist_sizes:
            # Build per-setlist manifest sizes
            for parent, data in chart_folders.items():
                if not data["is_chart"]:
                    continue
                # Extract setlist name from path (first component)
                first_slash = parent.find("/")
                setlist_name = parent[:first_slash] if first_slash != -1 else parent
                setlist_manifest_sizes[setlist_name] = setlist_manifest_sizes.get(setlist_name, 0) + data["total_size"]

        # Count charts (folders with markers or archives)
        for parent, data in chart_folders.items():
            if not data["is_chart"]:
                continue

            status.total_charts += 1

            # For custom folders with scanned data, skip per-chart processing
            # We'll use the scan results and calculate total_size per-setlist below
            if synced_from_scan is not None:
                continue

            # For archive charts, check sync_state
            if data["archive_name"]:
                is_synced, extracted_size = _check_archive_synced(
                    sync_state, folder_name, data["checksum_path"], data["archive_name"], data["archive_md5"]
                )
                if is_synced:
                    status.synced_charts += 1
                    # Use extracted size for both synced and total (consistent disk usage)
                    size_to_use = extracted_size if extracted_size else data["total_size"]
                    status.synced_size += size_to_use
                    status.total_size += size_to_use
                else:
                    # Not synced - use manifest size (what they'll download)
                    status.total_size += data["total_size"]
                continue

            # For folder charts, check if all files exist locally (using pre-scanned data)
            all_synced = True
            for file_path, file_size in data["files"]:
                local_size = local_files.get(file_path)
                if local_size != file_size:
                    all_synced = False
                    break

            if all_synced:
                status.synced_charts += 1
                status.synced_size += data["total_size"]
            status.total_size += data["total_size"]

        # For custom folders, use scan results for synced counts
        # Calculate total_size: disk size for downloaded setlists, manifest size for not-downloaded
        if synced_from_scan is not None:
            actual_charts, actual_size = synced_from_scan
            status.synced_charts += actual_charts
            status.synced_size += actual_size

            # Calculate total_size per setlist:
            # - Downloaded setlists: use actual disk size
            # - Not downloaded setlists: use manifest size
            for setlist_name, manifest_size in setlist_manifest_sizes.items():
                if setlist_name in downloaded_setlist_sizes:
                    # Downloaded - use disk size
                    status.total_size += downloaded_setlist_sizes[setlist_name]
                else:
                    # Not downloaded - use manifest size
                    status.total_size += manifest_size

        # Adjustment for nested archives: use get_best_stats() which checks
        # local scan > overrides > manifest for each setlist's chart count.
        # This handles Guitar Hero where 1 archive = 86 charts inside.
        subfolders = folder.get("subfolders", [])
        if subfolders and not is_custom:
            # Sum up chart counts for ENABLED setlists using get_best_stats
            best_total_charts = 0
            for sf in subfolders:
                sf_name = sf.get("name", "")
                # Check if this setlist is enabled
                if user_settings and not user_settings.is_subfolder_enabled(folder_id, sf_name):
                    continue
                sf_manifest_charts = sf.get("charts", {}).get("total", 0)
                sf_manifest_size = sf.get("total_size", 0)

                # Use get_best_stats to get override or local scan count
                sf_best_charts, _ = get_best_stats(
                    folder_name=folder_name,
                    setlist_name=sf_name,
                    manifest_charts=sf_manifest_charts,
                    manifest_size=sf_manifest_size,
                    local_path=folder_path if folder_path.exists() else None,
                )
                best_total_charts += sf_best_charts

            # Count how many charts we computed for THIS folder (1 per archive/folder)
            folder_computed_charts = sum(1 for _, d in chart_folders.items() if d["is_chart"])
            folder_synced_charts = 0
            for parent, data in chart_folders.items():
                if not data["is_chart"]:
                    continue
                if data["archive_name"]:
                    is_synced, _ = _check_archive_synced(
                        sync_state, folder_name, data["checksum_path"], data["archive_name"], data["archive_md5"]
                    )
                    if is_synced:
                        folder_synced_charts += 1
                else:
                    # Folder chart - check if synced
                    all_synced = all(local_files.get(fp) == fs for fp, fs in data["files"])
                    if all_synced:
                        folder_synced_charts += 1

            # If best stats has more charts than computed, we have nested archives
            # (1 archive = many songs inside, like Guitar Hero)
            if best_total_charts > folder_computed_charts:
                # Adjust totals: remove computed, add best stats
                status.total_charts -= folder_computed_charts
                status.total_charts += best_total_charts

                # For synced: if all archives are synced, assume all nested charts are synced
                if folder_synced_charts == folder_computed_charts and folder_computed_charts > 0:
                    status.synced_charts -= folder_synced_charts
                    status.synced_charts += best_total_charts

    return status
