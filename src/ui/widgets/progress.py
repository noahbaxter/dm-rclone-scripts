"""
Download progress display for DM Chart Sync.

Tracks folder/chart completion and coordinates display output.
"""

import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ...core.constants import CHART_MARKERS
from ...core.formatting import extract_path_context
from ...core.progress import ProgressTracker
from ..primitives.colors import Colors
from .active_downloads import ActiveDownloadsDisplay


@dataclass
class DownloadError:
    """Records a download error for summary."""
    path_context: str
    filename: str
    reason: str


class FolderProgress(ProgressTracker):
    """Progress tracker with split display: scrolling completions + fixed active downloads."""

    def __init__(self, total_files: int, total_folders: int):
        super().__init__()
        self.total_files = total_files
        self.total_folders = total_folders
        self.total_charts = 0
        self.completed_files = 0
        self.completed_charts = 0
        self.start_time = time.time()

        # Aggregate byte tracking for speed/ETA
        self.total_bytes = 0
        self.downloaded_bytes = 0

        self.folder_progress = {}
        self.errors: list[DownloadError] = []

        # TTY check only for ANSI cursor manipulation (active downloads section)
        self._is_tty = sys.__stdout__.isatty() if sys.__stdout__ else False
        self._active_display = ActiveDownloadsDisplay(is_tty=self._is_tty)

    def set_aggregate_totals(self, total_files: int, total_bytes: int, drive_name: str = ""):
        """Set totals for aggregate progress display."""
        self.total_files = total_files
        self.total_bytes = total_bytes
        self._active_display.set_aggregate_totals(total_files, total_bytes, drive_name)

    def register_folders(self, tasks):
        """Register all folders and their expected file counts."""
        folder_files = {}
        for task in tasks:
            folder = str(task.local_path.parent)
            if folder not in folder_files:
                folder_files[folder] = {"files": [], "archives": [], "rel_paths": []}
            filename = task.local_path.name.lower()
            folder_files[folder]["files"].append(filename)
            folder_files[folder]["rel_paths"].append(task.rel_path)
            if task.is_archive:
                display_name = task.local_path.name
                if display_name.startswith("_download_"):
                    display_name = display_name[10:]
                folder_files[folder]["archives"].append(display_name)

        for folder, data in folder_files.items():
            filenames = data["files"]
            archives = data["archives"]
            rel_paths = data["rel_paths"]

            archive_count = len(archives)
            has_markers = bool(set(filenames) & CHART_MARKERS)
            is_chart = has_markers and archive_count == 0

            self.folder_progress[folder] = {
                "expected": len(filenames),
                "completed": 0,
                "is_chart": is_chart,
                "path_context": extract_path_context(rel_paths[0] if rel_paths else None),
            }

            if archive_count > 0:
                self.total_charts += archive_count
            elif is_chart:
                self.total_charts += 1

        self.total_folders = len(folder_files)

    # Active download tracking (delegates to ActiveDownloadsDisplay)
    def register_active_download(self, file_id: str, display_name: str, path_context: str, total_bytes: int):
        with self.lock:
            self._active_display.register(file_id, display_name, path_context, total_bytes)

    def update_active_download(self, file_id: str, downloaded_bytes: int):
        with self.lock:
            self._active_display.update(file_id, downloaded_bytes)
            self._active_display.refresh()

    def unregister_active_download(self, file_id: str):
        with self.lock:
            self._active_display.unregister(file_id)

    def add_downloaded_bytes(self, bytes_count: int):
        """Add to the total downloaded bytes and update aggregate display."""
        with self.lock:
            self.downloaded_bytes += bytes_count
            self._active_display.update_aggregate_progress(self.completed_files, self.downloaded_bytes)

    # Error tracking (internal, caller must hold lock)
    def _record_error(self, path_context: str, filename: str, reason: str):
        self.errors.append(DownloadError(path_context, filename, reason))

    # Display helpers
    def _format_completion_line(self, path_context: str, item_name: str) -> str:
        c = Colors
        pct = (self.completed_charts / self.total_charts * 100) if self.total_charts > 0 else 0
        count_width = len(str(self.total_charts))
        count_str = f"({self.completed_charts:>{count_width}}/{self.total_charts})"
        ctx_part = f"{c.DIM}[{path_context}]{c.RESET}" if path_context else ""

        term_width = shutil.get_terminal_size().columns
        prefix_len = 8 + len(count_str) + 2
        remaining = max(10, term_width - prefix_len - len(path_context) - 4)
        if len(item_name) > remaining:
            item_name = item_name[:remaining - 3] + "..."

        return f"  {c.GREEN}{pct:5.1f}%{c.RESET} {count_str} {ctx_part} {item_name}"

    def _format_error_line(self, path_context: str, message: str) -> str:
        c = Colors
        ctx_part = f"{c.DIM}[{path_context}]{c.RESET}" if path_context else ""
        return f"  {c.RED}ERR:{c.RESET}          {ctx_part} {message}"

    def _print_with_active_section(self, line: str):
        """Print a line, managing the active downloads section."""
        try:
            if self._is_tty:
                self._active_display.clear_display()
            print(line)
            if self._is_tty:
                self._active_display.refresh()
        except OSError:
            # Terminal closed/piped mid-operation - ignore display errors
            pass

    # Public print methods
    def write(self, msg: str):
        with self.lock:
            if self._closed:
                return
            self._print_with_active_section(msg)

    def _print_completion(self, item_name: str, path_context: str = ""):
        """Internal: print completion line. Caller must hold lock."""
        if self._closed:
            return
        line = self._format_completion_line(path_context, item_name)
        self._print_with_active_section(line)

    def print_error(self, path_context: str, message: str):
        with self.lock:
            if self._closed:
                return
            # Extract reason and filename for summary (format: "REASON: filename")
            if ":" in message:
                reason, filename = message.split(":", 1)
                reason = reason.strip()
                filename = filename.strip()
            else:
                reason = "error"
                filename = message
            self._record_error(path_context, filename, reason)

            line = self._format_error_line(path_context, message)
            self._print_with_active_section(line)

    # Completion tracking
    def archive_completed(self, local_path: Path, archive_name: str, path_context: str = ""):
        with self.lock:
            if self._closed:
                return
            folder = str(local_path.parent)
            if folder in self.folder_progress and not path_context:
                path_context = self.folder_progress[folder].get("path_context", "")
            self.completed_charts += 1
            self._print_completion(archive_name, path_context)

    def file_completed(self, local_path: Path) -> tuple[str, bool, str] | None:
        with self.lock:
            if self._closed:
                return None
            self.completed_files += 1
            folder = str(local_path.parent)

            if folder in self.folder_progress:
                self.folder_progress[folder]["completed"] += 1
                prog = self.folder_progress[folder]
                if prog["completed"] >= prog["expected"] and prog["is_chart"]:
                    self.completed_charts += 1
                    return (local_path.parent.name, True, prog.get("path_context", ""))
            return None

    def print_folder_complete(self, folder_name: str, is_chart: bool, path_context: str = ""):
        with self.lock:
            if self._closed or not is_chart:
                return
            self._print_completion(folder_name, path_context)

    def close(self):
        with self.lock:
            if self._is_tty:
                self._active_display.clear_display()
            self._closed = True

    def print_error_summary(self):
        """Print a summary of all errors at the end."""
        if not self.errors:
            return

        c = Colors
        print()
        print(f"{c.RED}Download errors:{c.RESET}")

        grouped: dict[str, list[DownloadError]] = {}
        for err in self.errors:
            key = err.path_context or "Unknown"
            grouped.setdefault(key, []).append(err)

        total = len(self.errors)

        if total < 20:
            for ctx, errs in sorted(grouped.items()):
                print(f"  {c.DIM}[{ctx}]{c.RESET} {len(errs)} failed:")
                for err in errs:
                    print(f"    - {err.filename} ({err.reason})")
        elif total < 100:
            for ctx, errs in sorted(grouped.items()):
                print(f"  {c.DIM}[{ctx}]{c.RESET} {len(errs)} failed:")
                for err in errs[:3]:
                    print(f"    - {err.filename} ({err.reason})")
                if len(errs) > 3:
                    print(f"    ... and {len(errs) - 3} more")
        else:
            for ctx, errs in sorted(grouped.items()):
                print(f"  {c.DIM}[{ctx}]{c.RESET} {len(errs)} failed")

        print()
