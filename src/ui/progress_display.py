"""
Download progress display for DM Chart Sync.

Handles rendering download progress with chart/folder completion tracking.
"""

import shutil
import time
from pathlib import Path

from ..constants import CHART_MARKERS
from ..sync.progress import ProgressTracker


class FolderProgress(ProgressTracker):
    """
    Progress tracker that reports completed folders/charts/archives.

    Groups files by their parent folder and prints when each folder completes.
    Also tracks individual archive completions within folders.
    """

    def __init__(self, total_files: int, total_folders: int):
        super().__init__()
        self.total_files = total_files
        self.total_folders = total_folders
        self.total_charts = 0  # Total chart folders OR individual archives
        self.completed_files = 0
        self.completed_charts = 0
        self.start_time = time.time()

        # Track files per folder: {folder_path: {expected: int, completed: int, is_chart: bool, archive_count: int}}
        self.folder_progress = {}

    def register_folders(self, tasks):
        """Register all folders and their expected file counts."""
        folder_files = {}
        for task in tasks:
            folder = str(task.local_path.parent)
            if folder not in folder_files:
                folder_files[folder] = {"files": [], "archives": []}
            filename = task.local_path.name.lower()
            folder_files[folder]["files"].append(filename)
            if task.is_archive:
                # Store original name for display
                display_name = task.local_path.name
                if display_name.startswith("_download_"):
                    display_name = display_name[10:]
                folder_files[folder]["archives"].append(display_name)

        for folder, data in folder_files.items():
            filenames = data["files"]
            archives = data["archives"]

            # Check for chart markers (song.ini, notes.mid, etc.)
            has_markers = bool(set(filenames) & CHART_MARKERS)
            archive_count = len(archives)

            # A folder with archives: each archive counts as a chart
            # A folder with markers (no archives): the folder itself is one chart
            if archive_count > 0:
                self.folder_progress[folder] = {
                    "expected": len(filenames),
                    "completed": 0,
                    "is_chart": False,  # Don't report folder completion
                    "archive_count": archive_count,
                    "archives_completed": 0,
                }
                self.total_charts += archive_count
            elif has_markers:
                self.folder_progress[folder] = {
                    "expected": len(filenames),
                    "completed": 0,
                    "is_chart": True,
                    "archive_count": 0,
                    "archives_completed": 0,
                }
                self.total_charts += 1
            else:
                # Non-chart folder
                self.folder_progress[folder] = {
                    "expected": len(filenames),
                    "completed": 0,
                    "is_chart": False,
                    "archive_count": 0,
                    "archives_completed": 0,
                }

        self.total_folders = len(folder_files)

    def archive_completed(self, local_path: Path, archive_name: str):
        """Mark an archive as completed and print progress."""
        with self.lock:
            if self._closed:
                return

            folder = str(local_path.parent)
            if folder in self.folder_progress:
                self.folder_progress[folder]["archives_completed"] += 1

            self.completed_charts += 1
            self._print_item_complete(archive_name)

    def file_completed(self, local_path: Path) -> tuple[str, bool] | None:
        """
        Mark a file as completed. Returns (folder_name, is_chart) if folder is now complete.
        For archives, returns None (they're reported via archive_completed instead).
        """
        with self.lock:
            if self._closed:
                return None

            self.completed_files += 1
            folder = str(local_path.parent)

            if folder in self.folder_progress:
                self.folder_progress[folder]["completed"] += 1

                # Check if folder is complete (only for non-archive chart folders)
                prog = self.folder_progress[folder]
                if prog["completed"] >= prog["expected"] and prog["is_chart"]:
                    self.completed_charts += 1
                    return (local_path.parent.name, True)

            return None

    def _print_item_complete(self, item_name: str):
        """Print progress when a chart or archive completes."""
        if self._closed:
            return

        term_width = shutil.get_terminal_size().columns
        pct = (self.completed_charts / self.total_charts * 100) if self.total_charts > 0 else 0

        core = f"  {pct:5.1f}% ({self.completed_charts}/{self.total_charts})"

        remaining = term_width - len(core) - 5
        if remaining > 10:
            if len(item_name) > remaining:
                item_name = item_name[:remaining-3] + "..."
            line = f"{core}  {item_name}"
        else:
            line = core

        print(line)

    def print_folder_complete(self, folder_name: str, is_chart: bool):
        """Print progress when a chart folder completes."""
        with self.lock:
            if self._closed:
                return

            # Only print charts, skip non-chart folders silently
            if not is_chart:
                return

            self._print_item_complete(folder_name)
