"""
File downloader for DM Chart Sync.

Handles parallel file downloads with progress tracking and retries.
"""

import json
import os
import sys
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests

from ..constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS, VIDEO_EXTENSIONS
from ..file_ops import file_exists_with_size
from .progress import ProgressTracker

# Optional archive format support
try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False

try:
    from unrar import rarfile as unrar_rarfile
    # Test that the library is actually available
    unrar_rarfile.RarFile
    HAS_RAR_LIB = True
except (ImportError, LookupError):
    HAS_RAR_LIB = False

# Check for CLI tools as fallback for RAR extraction
RAR_CLI_TOOL = None
for tool in ["unrar", "unar"]:
    if shutil.which(tool):
        RAR_CLI_TOOL = tool
        break

# Checksum file for tracking archive chart state
CHECKSUM_FILE = "check.txt"

# Platform-specific imports for ESC detection
if os.name == 'nt':
    import msvcrt
else:
    import termios
    import tty
    import select


class EscMonitor:
    """Background thread that monitors for ESC key presses."""

    def __init__(self, on_esc: Callable[[], None]):
        self.on_esc = on_esc
        self._stop = threading.Event()
        self._thread = None
        self._old_settings = None

    def start(self):
        """Start monitoring for ESC."""
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop monitoring."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)

    def _monitor(self):
        """Monitor loop - checks for ESC key."""
        if os.name == 'nt':
            while not self._stop.is_set():
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\x1b':  # ESC
                        self.on_esc()
                        return
                time.sleep(0.05)
        else:
            fd = sys.stdin.fileno()
            try:
                self._old_settings = termios.tcgetattr(fd)
                # Use cbreak mode instead of raw - preserves output processing
                tty.setcbreak(fd)

                while not self._stop.is_set():
                    # Check for input with short timeout
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        ch = sys.stdin.read(1)
                        if ch == '\x1b':  # ESC
                            self.on_esc()
                            return
            finally:
                if self._old_settings:
                    termios.tcsetattr(fd, termios.TCSADRAIN, self._old_settings)


# =============================================================================
# Archive handling helpers
# =============================================================================

def read_checksum(folder_path: Path) -> str:
    """Read stored MD5 from check.txt."""
    checksum_path = folder_path / CHECKSUM_FILE
    if not checksum_path.exists():
        return ""
    try:
        with open(checksum_path) as f:
            data = json.load(f)
            return data.get("md5", "")
    except (json.JSONDecodeError, IOError):
        return ""


def write_checksum(folder_path: Path, md5: str, archive_name: str, extracted_size: int = 0):
    """Write MD5 and extracted size to check.txt."""
    checksum_path = folder_path / CHECKSUM_FILE
    folder_path.mkdir(parents=True, exist_ok=True)
    with open(checksum_path, "w") as f:
        json.dump({"md5": md5, "archive": archive_name, "size": extracted_size}, f)


def read_checksum_data(folder_path: Path) -> dict:
    """Read full check.txt data including size."""
    checksum_path = folder_path / CHECKSUM_FILE
    if not checksum_path.exists():
        return {}
    try:
        with open(checksum_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def get_folder_size(folder_path: Path) -> int:
    """Calculate total size of all files in folder (excluding check.txt)."""
    total = 0
    for f in folder_path.rglob("*"):
        if f.is_file() and f.name != CHECKSUM_FILE:
            try:
                total += f.stat().st_size
            except Exception:
                pass
    return total


def extract_archive(archive_path: Path, dest_folder: Path) -> Tuple[bool, str]:
    """
    Extract archive to destination folder.

    Returns (success, error_message).
    """
    ext = archive_path.suffix.lower()
    try:
        if ext == ".zip":
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(dest_folder)
        elif ext == ".7z":
            if not HAS_7Z:
                return False, "py7zr not installed (pip install py7zr)"
            with py7zr.SevenZipFile(archive_path, 'r') as sz:
                sz.extractall(dest_folder)
        elif ext == ".rar":
            import subprocess
            if HAS_RAR_LIB:
                # Use UnRAR library (fastest)
                with unrar_rarfile.RarFile(str(archive_path)) as rf:
                    rf.extractall(str(dest_folder))
            elif RAR_CLI_TOOL == "unrar":
                # Use unrar CLI
                result = subprocess.run(
                    ["unrar", "x", "-o+", str(archive_path), str(dest_folder) + "/"],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    return False, f"unrar failed: {result.stderr}"
            elif RAR_CLI_TOOL == "unar":
                # Use unar CLI (macOS)
                result = subprocess.run(
                    ["unar", "-f", "-o", str(dest_folder), str(archive_path)],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    return False, f"unar failed: {result.stderr}"
            else:
                return False, "RAR support unavailable (install unrar or unar)"
        else:
            return False, f"Unknown archive type: {ext}"
        return True, ""
    except Exception as e:
        return False, str(e)


def delete_video_files(folder_path: Path) -> int:
    """
    Delete video files from folder recursively.

    Returns count of deleted files.
    """
    deleted = 0
    for f in folder_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass  # Non-fatal
    return deleted


def is_archive_file(filename: str) -> bool:
    """Check if a filename is an archive type we handle."""
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


class FolderProgress(ProgressTracker):
    """
    Progress tracker that reports completed folders/charts.

    Groups files by their parent folder and prints when each folder completes.
    Distinguishes between chart folders (with song.ini/notes) and regular folders.
    """

    def __init__(self, total_files: int, total_folders: int):
        super().__init__()
        self.total_files = total_files
        self.total_folders = total_folders
        self.total_charts = 0
        self.completed_files = 0
        self.completed_charts = 0
        self.start_time = time.time()

        # Track files per folder: {folder_path: {expected: int, completed: int, is_chart: bool}}
        self.folder_progress = {}

    def register_folders(self, tasks):
        """Register all folders and their expected file counts."""
        folder_files = {}
        for task in tasks:
            folder = str(task.local_path.parent)
            if folder not in folder_files:
                folder_files[folder] = []
            folder_files[folder].append(task.local_path.name.lower())

        for folder, filenames in folder_files.items():
            # Check for chart markers (song.ini, notes.mid, etc.)
            has_markers = bool(set(filenames) & CHART_MARKERS)
            # Check for archive files (.zip, .7z, .rar)
            has_archives = any(
                f.endswith(tuple(CHART_ARCHIVE_EXTENSIONS)) for f in filenames
            )
            is_chart = has_markers or has_archives

            self.folder_progress[folder] = {
                "expected": len(filenames),
                "completed": 0,
                "is_chart": is_chart
            }
            if is_chart:
                self.total_charts += 1

        self.total_folders = len(folder_files)

    def file_completed(self, local_path: Path) -> tuple[str, bool] | None:
        """
        Mark a file as completed. Returns (folder_name, is_chart) if folder is now complete.
        """
        with self.lock:
            if self._closed:
                return None

            self.completed_files += 1
            folder = str(local_path.parent)

            if folder in self.folder_progress:
                self.folder_progress[folder]["completed"] += 1

                # Check if folder is complete
                if self.folder_progress[folder]["completed"] >= self.folder_progress[folder]["expected"]:
                    is_chart = self.folder_progress[folder]["is_chart"]
                    if is_chart:
                        self.completed_charts += 1
                    return (local_path.parent.name, is_chart)

            return None

    def print_folder_complete(self, folder_name: str, is_chart: bool):
        """Print progress when a folder completes."""
        with self.lock:
            if self._closed:
                return

            # Only print charts, skip non-chart folders silently
            if not is_chart:
                return

            term_width = shutil.get_terminal_size().columns
            pct = (self.completed_charts / self.total_charts * 100) if self.total_charts > 0 else 0

            core = f"  {pct:5.1f}% ({self.completed_charts}/{self.total_charts})"

            remaining = term_width - len(core) - 5
            if remaining > 10:
                if len(folder_name) > remaining:
                    folder_name = folder_name[:remaining-3] + "..."
                line = f"{core}  {folder_name}"
            else:
                line = core

            print(line)


@dataclass
class DownloadResult:
    """Result of a single file download."""
    success: bool
    file_path: Path
    message: str
    bytes_downloaded: int = 0


@dataclass
class DownloadTask:
    """A file to be downloaded."""
    file_id: str
    local_path: Path
    size: int = 0
    md5: str = ""
    is_archive: bool = False  # If True, needs extraction after download


class FileDownloader:
    """
    Parallel file downloader with progress tracking.

    Uses direct Google Drive download URLs. Can optionally use OAuth
    for files that require authentication.
    """

    DOWNLOAD_URL_TEMPLATE = "https://drive.google.com/uc?export=download&id={file_id}&confirm=1"
    API_DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

    def __init__(
        self,
        max_workers: int = 8,
        max_retries: int = 3,
        timeout: Tuple[int, int] = (10, 60),
        chunk_size: int = 32768,
        auth_token: Optional[str] = None,
        delete_videos: bool = True,
    ):
        """
        Initialize the downloader.

        Args:
            max_workers: Number of parallel download threads
            max_retries: Number of retry attempts per file
            timeout: Request timeout (connect, read)
            chunk_size: Download chunk size in bytes
            auth_token: Optional OAuth token for authenticated downloads
            delete_videos: Whether to delete video files from extracted archives
        """
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.auth_token = auth_token
        self.delete_videos = delete_videos
        self._print_lock = threading.Lock()

    def _download_with_auth(self, task: DownloadTask) -> requests.Response:
        """Download using Drive API with OAuth token."""
        url = f"{self.API_DOWNLOAD_URL.format(file_id=task.file_id)}&acknowledgeAbuse=true"
        headers = {"Authorization": f"Bearer {self.auth_token}"}
        return requests.get(
            url,
            stream=True,
            headers=headers,
            timeout=self.timeout
        )

    def _download_public(self, task: DownloadTask) -> requests.Response:
        """Download using public URL."""
        url = self.DOWNLOAD_URL_TEMPLATE.format(file_id=task.file_id)
        return requests.get(
            url,
            stream=True,
            allow_redirects=True,
            timeout=self.timeout
        )

    def download_file(self, task: DownloadTask) -> DownloadResult:
        """
        Download a single file with retries.

        Tries public URL first, falls back to OAuth if available.

        Args:
            task: DownloadTask with file info

        Returns:
            DownloadResult with success status and message
        """
        for attempt in range(self.max_retries):
            try:
                # Try public download first
                response = self._download_public(task)
                response.raise_for_status()

                # Check if we got HTML instead of the file (auth required)
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type:
                    # Try authenticated download if we have a token
                    if self.auth_token:
                        response = self._download_with_auth(task)
                        response.raise_for_status()
                    else:
                        return DownloadResult(
                            success=False,
                            file_path=task.local_path,
                            message=f"SKIP (auth required): {task.local_path.name}",
                        )

                # Create parent directories
                task.local_path.parent.mkdir(parents=True, exist_ok=True)

                # Download file
                downloaded_bytes = 0
                with open(task.local_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)

                return DownloadResult(
                    success=True,
                    file_path=task.local_path,
                    message=f"OK: {task.local_path.name}",
                    bytes_downloaded=downloaded_bytes,
                )

            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    continue
                return DownloadResult(
                    success=False,
                    file_path=task.local_path,
                    message=f"ERR (timeout): {task.local_path.name}",
                )

            except requests.exceptions.HTTPError as e:
                if hasattr(e, 'response') and e.response.status_code == 403:
                    # Try to get more detail from response
                    detail = ""
                    try:
                        err_json = e.response.json()
                        detail = err_json.get("error", {}).get("message", "")
                    except Exception:
                        pass
                    msg = f"SKIP (access denied): {task.local_path.name}"
                    if detail:
                        msg += f" - {detail}"
                    return DownloadResult(
                        success=False,
                        file_path=task.local_path,
                        message=msg,
                    )
                if attempt < self.max_retries - 1:
                    continue
                return DownloadResult(
                    success=False,
                    file_path=task.local_path,
                    message=f"ERR (HTTP): {task.local_path.name}",
                )

            except Exception as e:
                if attempt < self.max_retries - 1:
                    continue
                return DownloadResult(
                    success=False,
                    file_path=task.local_path,
                    message=f"ERR: {task.local_path.name} - {e}",
                )

        return DownloadResult(
            success=False,
            file_path=task.local_path,
            message=f"ERR: {task.local_path.name} - failed after {self.max_retries} attempts",
        )

    def process_archive(self, task: DownloadTask) -> Tuple[bool, str]:
        """
        Process a downloaded archive: extract, write checksum, delete videos, cleanup.

        Args:
            task: The completed DownloadTask (is_archive should be True)

        Returns:
            (success, error_message)
        """
        archive_path = task.local_path
        chart_folder = archive_path.parent

        # Extract archive
        success, error = extract_archive(archive_path, chart_folder)
        if not success:
            return False, f"Extract failed: {error}"

        # Delete video files if enabled
        if self.delete_videos:
            delete_video_files(chart_folder)

        # Calculate extracted size (after video deletion)
        extracted_size = get_folder_size(chart_folder)

        # Write checksum with size
        archive_name = archive_path.name.replace("_download_", "", 1)
        write_checksum(chart_folder, task.md5, archive_name, extracted_size)

        # Delete the archive
        try:
            archive_path.unlink()
        except Exception:
            pass  # Non-fatal

        return True, ""

    def download_many(
        self,
        tasks: List[DownloadTask],
        progress_callback: Optional[Callable[[DownloadResult], None]] = None,
        show_progress: bool = True,
    ) -> Tuple[int, int, int, bool]:
        """
        Download multiple files in parallel.

        Args:
            tasks: List of DownloadTask objects
            progress_callback: Optional callback for each completed download
            show_progress: Whether to show tqdm progress bar

        Returns:
            Tuple of (downloaded_count, skipped_count, error_count, cancelled)
        """
        if not tasks:
            return 0, 0, 0, False

        downloaded = 0
        errors = 0
        cancelled = False

        progress = None
        if show_progress:
            progress = FolderProgress(total_files=len(tasks), total_folders=0)
            progress.register_folders(tasks)
            print(f"  Downloading {len(tasks)} files across {progress.total_folders} charts...")
            print(f"  (Press ESC to cancel)")
            print()

        # Set up Ctrl+C handler for cancellation
        original_handler = None
        import signal

        def handle_cancel():
            nonlocal cancelled
            if not cancelled:
                cancelled = True
                if progress:
                    progress.cancel()
                print("\n  Cancelling downloads...")

        def handle_interrupt(signum, frame):
            handle_cancel()

        try:
            original_handler = signal.signal(signal.SIGINT, handle_interrupt)
        except Exception:
            pass  # Signal handling not available

        # Start ESC key monitor
        esc_monitor = EscMonitor(on_esc=handle_cancel)
        esc_monitor.start()

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self.download_file, task): task
                    for task in tasks
                }

                for future in as_completed(futures):
                    # Check for cancellation
                    if cancelled or (progress and progress.cancelled):
                        # Cancel remaining futures
                        for f in futures:
                            f.cancel()
                        break

                    task = futures[future]
                    try:
                        result = future.result()

                        if result.success:
                            # Process archive if needed
                            if task.is_archive:
                                archive_success, archive_error = self.process_archive(task)
                                if not archive_success:
                                    errors += 1
                                    if progress:
                                        progress.file_completed(task.local_path)
                                        progress.write(f"  ERR: {task.local_path.parent.name} - {archive_error}")
                                    continue

                            downloaded += 1
                            if progress:
                                completed_info = progress.file_completed(task.local_path)
                                if completed_info:
                                    folder_name, is_chart = completed_info
                                    progress.print_folder_complete(folder_name, is_chart)
                        else:
                            errors += 1
                            if progress:
                                progress.file_completed(task.local_path)  # Still count it
                                progress.write(f"  {result.message}")

                        if progress_callback:
                            progress_callback(result)

                    except Exception as e:
                        errors += 1
                        if progress:
                            progress.file_completed(task.local_path)
                            progress.write(f"  ERR: {task.local_path.name} - {e}")

        except KeyboardInterrupt:
            # Handle any remaining Ctrl+C during cleanup
            cancelled = True

        finally:
            # Stop ESC monitor
            esc_monitor.stop()

            # Restore original signal handler
            try:
                signal.signal(signal.SIGINT, original_handler or signal.SIG_DFL)
            except Exception:
                pass

            if progress:
                progress.close()
            if cancelled:
                print(f"  Cancelled. Downloaded {downloaded} files ({progress.completed_charts if progress else 0} complete charts).")

        return downloaded, 0, errors, cancelled

    @staticmethod
    def filter_existing(
        files: List[dict],
        local_base: Path,
    ) -> Tuple[List[DownloadTask], int]:
        """
        Filter files that already exist locally.

        For regular files: check if exists with matching size.
        For archives: check if check.txt has matching MD5.

        Args:
            files: List of file dicts with id, path, size keys
            local_base: Base path for local files

        Returns:
            Tuple of (tasks_to_download, skipped_count)
        """
        to_download = []
        skipped = 0

        for f in files:
            file_path = f["path"]
            file_name = file_path.split("/")[-1] if "/" in file_path else file_path
            file_size = f.get("size", 0)
            file_md5 = f.get("md5", "")

            if is_archive_file(file_name):
                # Archive file: check MD5 in check.txt
                # The chart folder is the parent of where the archive would be
                local_path = local_base / file_path
                chart_folder = local_path.parent

                stored_md5 = read_checksum(chart_folder)
                if stored_md5 and stored_md5 == file_md5:
                    # Already extracted with matching checksum
                    skipped += 1
                else:
                    # Need to download and extract
                    # Download to temp location within chart folder
                    download_path = chart_folder / f"_download_{file_name}"
                    to_download.append(DownloadTask(
                        file_id=f["id"],
                        local_path=download_path,
                        size=file_size,
                        md5=file_md5,
                        is_archive=True,
                    ))
            else:
                # Regular file: check if exists with matching size
                local_path = local_base / file_path
                if file_exists_with_size(local_path, file_size):
                    skipped += 1
                else:
                    to_download.append(DownloadTask(
                        file_id=f["id"],
                        local_path=local_path,
                        size=file_size,
                        md5=file_md5,
                    ))

        return to_download, skipped
