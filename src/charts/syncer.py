"""
Chart syncer - handles downloading and syncing charts.

Uses the Chart abstraction to handle different chart types uniformly.
"""

import signal
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .base import Chart, ChartType, ChartState


class ChartProgress:
    """
    Progress tracker for chart syncing.

    Reports progress at the chart level, not file level.
    """

    def __init__(self, total_charts: int):
        self.total_charts = total_charts
        self.completed_charts = 0
        self.total_files = 0
        self.completed_files = 0
        self.start_time = time.time()
        self.lock = threading.Lock()
        self._closed = False
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        """Signal cancellation."""
        self._cancelled = True

    def chart_started(self, chart: Chart):
        """Called when a chart starts downloading."""
        with self.lock:
            self.total_files += chart.file_count

    def file_completed(self):
        """Called when a file completes downloading."""
        with self.lock:
            self.completed_files += 1

    def chart_completed(self, chart: Chart):
        """Called when a chart completes downloading."""
        with self.lock:
            if self._closed:
                return

            self.completed_charts += 1
            elapsed = time.time() - self.start_time
            rate = self.completed_files / elapsed if elapsed > 0 else 0
            pct = (self.completed_charts / self.total_charts * 100) if self.total_charts > 0 else 0

            # Print progress line
            term_width = shutil.get_terminal_size().columns
            type_str = f"[{chart.chart_type.value}]" if chart.chart_type != ChartType.FOLDER else ""
            core = f"  {pct:5.1f}% ({self.completed_charts}/{self.total_charts} charts, {rate:.1f} files/s)"

            remaining = term_width - len(core) - len(type_str) - 5
            name = chart.name
            if len(name) > remaining:
                name = name[:remaining-3] + "..."

            if type_str:
                print(f"{core}  {type_str} {name}")
            else:
                print(f"{core}  {name}")

    def write(self, msg: str):
        """Write a message."""
        with self.lock:
            print(msg)

    def close(self):
        """Close the progress tracker."""
        with self.lock:
            self._closed = True


class ChartSyncer:
    """
    Syncs charts from Google Drive.

    Handles different chart types (folder, zip, sng) with appropriate
    download and post-processing logic.
    """

    DOWNLOAD_URL_TEMPLATE = "https://drive.google.com/uc?export=download&id={file_id}&confirm=1"

    def __init__(
        self,
        max_workers: int = 8,
        max_retries: int = 3,
        timeout: Tuple[int, int] = (10, 60),
        chunk_size: int = 32768,
    ):
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.timeout = timeout
        self.chunk_size = chunk_size
        self._print_lock = threading.Lock()

    def download_file(self, file_id: str, local_path: Path, expected_size: int = 0) -> bool:
        """
        Download a single file from Google Drive.

        Returns True if successful, False otherwise.
        """
        url = self.DOWNLOAD_URL_TEMPLATE.format(file_id=file_id)

        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    stream=True,
                    allow_redirects=True,
                    timeout=self.timeout
                )
                response.raise_for_status()

                # Check if we got HTML instead of the file
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type:
                    return False

                # Create parent directories
                local_path.parent.mkdir(parents=True, exist_ok=True)

                # Download file
                with open(local_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)

                return True

            except Exception:
                if attempt < self.max_retries - 1:
                    continue
                return False

        return False

    def sync_chart(self, chart: Chart, progress: Optional[ChartProgress] = None) -> Tuple[int, int]:
        """
        Sync a single chart.

        Returns (files_downloaded, errors).
        """
        # Check if sync needed
        state = chart.check_state()
        if state == ChartState.CURRENT:
            return 0, 0

        # Prepare for sync (may delete folder for zip/sng updates)
        chart.prepare_for_sync()

        # Get download tasks
        tasks = chart.get_download_tasks()
        if not tasks:
            return 0, 0

        if progress:
            progress.chart_started(chart)

        downloaded = 0
        errors = 0

        # Download each file
        for task in tasks:
            if progress and progress.cancelled:
                break

            file_id = task["id"]
            local_path = task["local_path"]
            size = task.get("size", 0)

            success = self.download_file(file_id, local_path, size)

            if success:
                downloaded += 1
            else:
                errors += 1

            if progress:
                progress.file_completed()

        # Post-sync processing (extract zip, etc.)
        if errors == 0:
            try:
                chart.post_sync()
            except Exception as e:
                errors += 1
                if progress:
                    progress.write(f"  ERR: {chart.name} post-sync failed: {e}")

        return downloaded, errors

    def sync_charts(
        self,
        charts: List[Chart],
        show_progress: bool = True,
    ) -> Tuple[int, int, int]:
        """
        Sync multiple charts.

        Returns (charts_synced, files_downloaded, errors).
        """
        # Filter to charts that need syncing
        charts_to_sync = []
        for chart in charts:
            state = chart.check_state()
            if state != ChartState.CURRENT:
                charts_to_sync.append(chart)

        if not charts_to_sync:
            return 0, 0, 0

        progress = None
        if show_progress:
            progress = ChartProgress(total_charts=len(charts_to_sync))
            total_files = sum(chart.file_count for chart in charts_to_sync)
            print(f"  Syncing {len(charts_to_sync)} charts ({total_files} files)...")
            print()

        # Set up Ctrl+C handler
        original_handler = None
        cancelled = False

        def handle_interrupt(signum, frame):
            nonlocal cancelled
            if not cancelled:
                cancelled = True
                if progress:
                    progress.cancel()
                print("\n  Ctrl+C pressed - cancelling sync...")

        try:
            original_handler = signal.signal(signal.SIGINT, handle_interrupt)
        except Exception:
            pass

        charts_synced = 0
        total_downloaded = 0
        total_errors = 0

        try:
            for chart in charts_to_sync:
                if cancelled or (progress and progress.cancelled):
                    break

                downloaded, errors = self.sync_chart(chart, progress)

                if downloaded > 0 or errors == 0:
                    charts_synced += 1
                    if progress:
                        progress.chart_completed(chart)

                total_downloaded += downloaded
                total_errors += errors

        except KeyboardInterrupt:
            cancelled = True

        finally:
            try:
                signal.signal(signal.SIGINT, original_handler or signal.SIG_DFL)
            except Exception:
                pass

            if progress:
                progress.close()

            if cancelled:
                print(f"  Cancelled. Synced {charts_synced} charts ({total_downloaded} files).")

        return charts_synced, total_downloaded, total_errors

    def sync_charts_parallel(
        self,
        charts: List[Chart],
        show_progress: bool = True,
        max_concurrent_charts: int = 4,
    ) -> Tuple[int, int, int]:
        """
        Sync multiple charts with parallel file downloads within each chart.

        This is more complex but faster for charts with many files.

        Returns (charts_synced, files_downloaded, errors).
        """
        # For now, just use sequential sync
        # Parallel chart sync can be added later if needed
        return self.sync_charts(charts, show_progress)
