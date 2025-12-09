"""
File downloader for DM Chart Sync.

Handles parallel file downloads with progress tracking and retries.
Uses asyncio + aiohttp for efficient concurrent downloads.
"""

import asyncio
import json
import os
import ssl
import sys
import shutil
import signal
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Union
from dataclasses import dataclass

import aiohttp
import certifi

from ..constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS, VIDEO_EXTENSIONS
from ..file_ops import file_exists_with_size
from ..utils import sanitize_path
from .progress import ProgressTracker

# Windows MAX_PATH limit (260 chars including null terminator)
# Paths longer than this fail unless long path support is enabled in registry
WINDOWS_MAX_PATH = 260

# Large file threshold for reducing download concurrency (500MB)
# When downloading many large files, reduce parallelism to prevent bandwidth saturation
LARGE_FILE_THRESHOLD = 500_000_000


def get_certifi_path() -> str:
    """Get path to certifi CA bundle, handling PyInstaller bundles."""
    # Check if running from PyInstaller bundle
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running from PyInstaller bundle - look for bundled cert
        bundled_cert = os.path.join(sys._MEIPASS, 'certifi', 'cacert.pem')
        if os.path.exists(bundled_cert):
            return bundled_cert
    # Fall back to installed certifi
    return certifi.where()

# Optional archive format support
try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False

# Set up UnRAR library path for bundled binaries
def _setup_unrar_library():
    """Configure rarfile to use bundled UnRAR library."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running from PyInstaller bundle
        bundle_dir = sys._MEIPASS
        if os.name == 'nt':
            lib_path = os.path.join(bundle_dir, 'UnRAR64.dll')
        else:
            lib_path = os.path.join(bundle_dir, 'libunrar.dylib')
        if os.path.exists(lib_path):
            os.environ['UNRAR_LIB_PATH'] = lib_path
    else:
        # Development mode - check for libs folder
        dev_libs = Path(__file__).parent.parent.parent / 'libs' / 'bin'
        if os.name == 'nt':
            lib_path = dev_libs / 'UnRAR64.dll'
        else:
            lib_path = dev_libs / 'libunrar.dylib'
        if lib_path.exists():
            os.environ['UNRAR_LIB_PATH'] = str(lib_path)

_setup_unrar_library()

try:
    import rarfile
    HAS_RAR_LIB = True
except ImportError:
    HAS_RAR_LIB = False
    rarfile = None


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

def read_checksum(folder_path: Path, archive_name: str = None) -> str:
    """
    Read stored MD5 from check.txt.

    Args:
        folder_path: Path to folder containing check.txt
        archive_name: Optional archive name to look up (for multi-archive format)

    Returns:
        MD5 string, or empty string if not found
    """
    checksum_path = folder_path / CHECKSUM_FILE
    if not checksum_path.exists():
        return ""
    try:
        with open(checksum_path) as f:
            data = json.load(f)

            # New multi-archive format
            if "archives" in data and archive_name:
                archive_data = data["archives"].get(archive_name, {})
                return archive_data.get("md5", "")

            # Old single-archive format (backwards compat)
            return data.get("md5", "")
    except (json.JSONDecodeError, IOError):
        return ""


def write_checksum(
    folder_path: Path,
    md5: str,
    archive_name: str,
    archive_size: int = 0,
    extracted_size: int = 0,
    size_novideo: int = None,
    extracted_to: str = None
):
    """
    Write MD5 and size info to check.txt.

    Uses multi-archive format that stores all archives in one file.

    Args:
        folder_path: Path to folder for check.txt
        md5: MD5 hash of the archive
        archive_name: Name of the archive file
        archive_size: Size of the archive file (download size)
        extracted_size: Size after extraction (canonical size on disk)
        size_novideo: Size after video removal (only if different from extracted_size)
        extracted_to: Name of folder contents were extracted to (if different from archive)
    """
    checksum_path = folder_path / CHECKSUM_FILE
    folder_path.mkdir(parents=True, exist_ok=True)

    # Read existing data (if any)
    existing = {}
    if checksum_path.exists():
        try:
            with open(checksum_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Migrate old format to new format if needed
    if "archives" not in existing:
        archives = {}
        # Migrate old single-archive entry if present
        if "md5" in existing and "archive" in existing:
            old_name = existing["archive"]
            archives[old_name] = {
                "md5": existing["md5"],
                "size": existing.get("size", 0),
            }
        existing = {"archives": archives}

    # Add/update this archive
    archive_data = {
        "md5": md5,
        "archive_size": archive_size,
        "size": extracted_size,
    }
    # Only store size_novideo if videos were removed and size changed
    if size_novideo is not None and size_novideo != extracted_size:
        archive_data["size_novideo"] = size_novideo
    if extracted_to:
        archive_data["extracted_to"] = extracted_to

    existing["archives"][archive_name] = archive_data

    with open(checksum_path, "w") as f:
        json.dump(existing, f, indent=2)


def repair_checksum_sizes(folder_path: Path) -> Tuple[int, int]:
    """
    Repair check.txt files with missing/incorrect size data.

    Scans folder for check.txt files and updates them with actual sizes
    calculated from the extracted content on disk.

    Args:
        folder_path: Base folder to scan (e.g., Sync Charts/Guitar Hero)

    Returns:
        Tuple of (repaired_count, total_checked)
    """
    repaired = 0
    checked = 0

    for checksum_file in folder_path.rglob(CHECKSUM_FILE):
        chart_folder = checksum_file.parent
        checked += 1

        try:
            with open(checksum_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        if "archives" not in data:
            continue

        modified = False
        for archive_name, archive_info in data["archives"].items():
            # Check if size is missing or zero
            current_size = archive_info.get("size", 0)
            if current_size > 0:
                continue  # Already has valid size

            # Calculate actual size from disk
            # First, try to find the extracted folder by archive stem
            archive_stem = Path(archive_name).stem
            extracted_folder = chart_folder / archive_stem

            # Also check for _download_ prefixed folder (old bug)
            download_prefixed = chart_folder / f"_download_{archive_stem}"

            # Calculate size from whichever folder exists
            if extracted_folder.exists() and extracted_folder.is_dir():
                actual_size = get_folder_size(extracted_folder)
            elif download_prefixed.exists() and download_prefixed.is_dir():
                actual_size = get_folder_size(download_prefixed)
                # Rename the folder to fix the _download_ prefix issue
                try:
                    download_prefixed.rename(extracted_folder)
                except OSError:
                    pass  # Keep original name if rename fails
            else:
                # No extracted folder found, calculate from chart folder
                # (for archives that extract flat without a subfolder)
                actual_size = get_folder_size(chart_folder)

            if actual_size > 0:
                archive_info["size"] = actual_size
                modified = True

        if modified:
            with open(checksum_file, "w") as f:
                json.dump(data, f, indent=2)
            repaired += 1

    return repaired, checked


def read_checksum_data(folder_path: Path) -> dict:
    """
    Read full check.txt data.

    Returns dict with "archives" key containing all archive info.
    Handles both old and new formats.
    """
    checksum_path = folder_path / CHECKSUM_FILE
    if not checksum_path.exists():
        return {"archives": {}}
    try:
        with open(checksum_path) as f:
            data = json.load(f)

        # Already new format
        if "archives" in data:
            return data

        # Migrate old format on read
        if "md5" in data and "archive" in data:
            return {
                "archives": {
                    data["archive"]: {
                        "md5": data["md5"],
                        "size": data.get("size", 0),
                    }
                }
            }

        return {"archives": {}}
    except (json.JSONDecodeError, IOError):
        return {"archives": {}}


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
    Extract archive using Python libraries.

    Supports:
    - ZIP: zipfile (stdlib)
    - 7z: py7zr
    - RAR: rarfile with bundled UnRAR library

    Returns (success, error_message).
    """
    ext = archive_path.suffix.lower()
    try:
        if ext == ".zip":
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(dest_folder)
            return True, ""
        elif ext == ".7z":
            if not HAS_7Z:
                return False, "py7zr library not available"
            with py7zr.SevenZipFile(archive_path, 'r') as sz:
                sz.extractall(dest_folder)
            return True, ""
        elif ext == ".rar":
            if not HAS_RAR_LIB:
                return False, "rarfile library not available"
            with rarfile.RarFile(str(archive_path)) as rf:
                rf.extractall(str(dest_folder))
            return True, ""
        else:
            return False, f"Unsupported archive format: {ext}"
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


@dataclass
class DownloadResult:
    """Result of a single file download."""
    success: bool
    file_path: Path
    message: str
    bytes_downloaded: int = 0
    retryable: bool = False  # True if failure might succeed on retry (rate limit)


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
    Async file downloader with progress tracking.

    Uses asyncio + aiohttp for efficient concurrent downloads.
    Uses direct Google Drive download URLs. Can optionally use OAuth
    for files that require authentication.
    """

    DOWNLOAD_URL_TEMPLATE = "https://drive.google.com/uc?export=download&id={file_id}&confirm=1"
    API_DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

    def __init__(
        self,
        max_workers: int = 24,
        max_retries: int = 3,
        timeout: Tuple[int, int] = (10, 120),
        chunk_size: int = 32768,
        auth_token: Optional[Union[str, Callable[[], Optional[str]]]] = None,
        delete_videos: bool = True,
    ):
        """
        Initialize the downloader.

        Args:
            max_workers: Max concurrent downloads
            max_retries: Number of retry attempts per file
            timeout: Request timeout (connect, sock_read between chunks)
            chunk_size: Download chunk size in bytes
            auth_token: OAuth token string OR callable that returns fresh token
                        (callable allows token refresh for long downloads)
            delete_videos: Whether to delete video files from extracted archives
        """
        self.max_workers = max_workers
        self.max_retries = max_retries
        # Use sock_read timeout instead of total - allows indefinite downloads as long as
        # data keeps flowing. This prevents timeouts on large files (500MB+).
        self.timeout = aiohttp.ClientTimeout(connect=timeout[0], sock_read=timeout[1])
        self.chunk_size = chunk_size
        self._auth_token = auth_token
        self.delete_videos = delete_videos

    def _get_auth_token(self) -> Optional[str]:
        """Get current auth token, calling getter if it's a callable."""
        if callable(self._auth_token):
            return self._auth_token()
        return self._auth_token

    async def _download_file_async(
        self,
        session: aiohttp.ClientSession,
        task: DownloadTask,
        semaphore: asyncio.Semaphore,
        progress_tracker: Optional["FolderProgress"] = None,
    ) -> DownloadResult:
        """
        Download a single file with retries (async).

        Tries public URL first, falls back to OAuth if available.
        """
        # Get display name (strip _download_ prefix for archives)
        display_name = task.local_path.name
        if display_name.startswith("_download_"):
            display_name = display_name[10:]

        async with semaphore:
            for attempt in range(self.max_retries):
                try:
                    # Try public download first
                    url = self.DOWNLOAD_URL_TEMPLATE.format(file_id=task.file_id)
                    async with session.get(url, allow_redirects=True) as response:
                        response.raise_for_status()

                        # Check if we got HTML instead of the file (rate limit or auth required)
                        content_type = response.headers.get("content-type", "")
                        if "text/html" in content_type:
                            # Could be rate limiting - retry with backoff
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(1.0 * (attempt + 1))  # Longer backoff for rate limits
                                continue

                            # Last attempt - try authenticated download if available
                            auth_token = self._get_auth_token()
                            if auth_token:
                                api_url = f"{self.API_DOWNLOAD_URL.format(file_id=task.file_id)}&acknowledgeAbuse=true"
                                headers = {"Authorization": f"Bearer {auth_token}"}
                                async with session.get(api_url, headers=headers) as auth_response:
                                    auth_response.raise_for_status()
                                    return await self._write_response(auth_response, task, progress_tracker)
                            else:
                                return DownloadResult(
                                    success=False,
                                    file_path=task.local_path,
                                    message=f"SKIP (rate limited): {display_name}",
                                    retryable=True,  # Can retry later
                                )

                        return await self._write_response(response, task, progress_tracker)

                except asyncio.TimeoutError:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))  # Backoff
                        continue
                    return DownloadResult(
                        success=False,
                        file_path=task.local_path,
                        message=f"ERR (timeout): {display_name}",
                        retryable=True,
                    )

                except aiohttp.ClientResponseError as e:
                    # 401/403 can be genuine permission issues OR rate limiting in disguise
                    # Try OAuth if available, with backoff
                    auth_token = self._get_auth_token()
                    if e.status in (401, 403) and auth_token:
                        try:
                            # Brief backoff before OAuth attempt (rate limit mitigation)
                            await asyncio.sleep(0.5 * (attempt + 1))
                            api_url = f"{self.API_DOWNLOAD_URL.format(file_id=task.file_id)}&acknowledgeAbuse=true"
                            headers = {"Authorization": f"Bearer {auth_token}"}
                            async with session.get(api_url, headers=headers) as auth_response:
                                auth_response.raise_for_status()
                                return await self._write_response(auth_response, task, progress_tracker)
                        except aiohttp.ClientResponseError as auth_e:
                            # OAuth also failed - check if it's retryable
                            # 429/5xx are definitely rate limits, 403 often is too
                            is_retryable = auth_e.status in (403, 429) or 500 <= auth_e.status < 600
                            return DownloadResult(
                                success=False,
                                file_path=task.local_path,
                                message=f"ERR (auth failed, HTTP {auth_e.status}): {display_name}",
                                retryable=is_retryable,
                            )
                    # No OAuth or non-auth error
                    if e.status == 403:
                        # 403 without OAuth could still be rate limiting - mark retryable
                        return DownloadResult(
                            success=False,
                            file_path=task.local_path,
                            message=f"ERR (HTTP 403): {display_name}",
                            retryable=True,
                        )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    # 5xx errors are server-side - log file_id for investigation
                    # Mark as non-retryable to skip on this run (persistent failures indicate
                    # corrupted/deleted files that won't succeed with more retries)
                    if 500 <= e.status < 600:
                        return DownloadResult(
                            success=False,
                            file_path=task.local_path,
                            message=f"ERR (HTTP {e.status}): {display_name} [file_id={task.file_id}]",
                            retryable=False,  # Skip persistent server errors
                        )
                    return DownloadResult(
                        success=False,
                        file_path=task.local_path,
                        message=f"ERR (HTTP {e.status}): {display_name}",
                        retryable=False,
                    )

                except asyncio.CancelledError:
                    # Propagate cancellation
                    raise

                except Exception as e:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    return DownloadResult(
                        success=False,
                        file_path=task.local_path,
                        message=f"ERR: {display_name} - {e}",
                    )

            return DownloadResult(
                success=False,
                file_path=task.local_path,
                message=f"ERR: {display_name} - failed after {self.max_retries} attempts",
            )

    async def _write_response(
        self,
        response: aiohttp.ClientResponse,
        task: DownloadTask,
        progress_tracker: Optional["FolderProgress"] = None,
    ) -> DownloadResult:
        """Write response content to file."""
        # Create parent directories
        task.local_path.parent.mkdir(parents=True, exist_ok=True)

        downloaded_bytes = 0

        # For small files (<1MB), just read all at once
        # For larger files, stream in chunks
        content_length = response.content_length or 0

        if content_length > 0 and content_length < 1024 * 1024:
            # Small file - read all at once (faster for small files)
            data = await response.read()
            with open(task.local_path, "wb") as f:
                f.write(data)
            downloaded_bytes = len(data)
        else:
            # Larger file - stream to disk with progress updates
            # Use task.size if content_length is unreliable (Google Drive sometimes returns wrong values)
            total_size = task.size if task.size > 0 else content_length
            download_start = time.time()
            last_progress_time = download_start
            progress_interval = 1.5  # Report every 1.5 seconds
            time_threshold = 2.0  # Only show progress after file has been downloading this long

            # Get display name (strip _download_ prefix if present)
            display_name = task.local_path.name
            if display_name.startswith("_download_"):
                display_name = display_name[10:]

            with open(task.local_path, "wb") as f:
                async for chunk in response.content.iter_chunked(self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)

                        # Show progress only for files downloading longer than threshold
                        if progress_tracker:
                            now = time.time()
                            elapsed = now - download_start
                            if elapsed >= time_threshold and now - last_progress_time >= progress_interval:
                                last_progress_time = now
                                pct = (downloaded_bytes / total_size * 100) if total_size > 0 else 0
                                size_mb = downloaded_bytes / (1024 * 1024)
                                total_mb = total_size / (1024 * 1024)
                                progress_tracker.write(f"  ↓ {display_name}: {size_mb:.0f}/{total_mb:.0f} MB ({pct:.0f}%)")

        return DownloadResult(
            success=True,
            file_path=task.local_path,
            message=f"OK: {task.local_path.name}",
            bytes_downloaded=downloaded_bytes,
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

        # Determine extracted folder name (archive name without extension)
        archive_name = archive_path.name.replace("_download_", "", 1)
        archive_stem = Path(archive_name).stem
        extracted_folder = chart_folder / archive_stem

        # Rename archive to remove _download_ prefix BEFORE extraction
        # This ensures unar/7z create folders with the correct name
        if archive_path.name.startswith("_download_"):
            clean_archive_path = chart_folder / archive_name
            try:
                archive_path.rename(clean_archive_path)
                archive_path = clean_archive_path
            except OSError:
                pass  # Continue with original name if rename fails

        # Track archive size (download size)
        archive_size = task.size

        # Measure folder size BEFORE extraction to calculate delta
        size_before = get_folder_size(chart_folder)

        # Extract archive
        success, error = extract_archive(archive_path, chart_folder)
        if not success:
            return False, f"Extract failed: {error}"

        # Measure size AFTER extraction (before video removal)
        if extracted_folder.exists() and extracted_folder.is_dir():
            extracted_size = get_folder_size(extracted_folder)
        else:
            size_after_extract = get_folder_size(chart_folder)
            extracted_size = size_after_extract - size_before

        # Delete video files if enabled and measure size after
        size_novideo = None
        if self.delete_videos:
            # Delete videos in extracted folder if it exists, otherwise in chart_folder
            video_folder = extracted_folder if extracted_folder.exists() else chart_folder
            deleted_count = delete_video_files(video_folder)

            # Only measure if videos were actually deleted
            if deleted_count > 0:
                if extracted_folder.exists() and extracted_folder.is_dir():
                    size_novideo = get_folder_size(extracted_folder)
                else:
                    size_after_videos = get_folder_size(chart_folder)
                    size_novideo = size_after_videos - size_before

        # Write checksum with size info
        write_checksum(
            chart_folder,
            task.md5,
            archive_name,
            archive_size=archive_size,
            extracted_size=extracted_size,
            size_novideo=size_novideo
        )

        # Delete the archive
        try:
            archive_path.unlink()
        except Exception:
            pass  # Non-fatal

        return True, ""

    def _cleanup_partial_downloads(self, tasks: List[DownloadTask]) -> int:
        """
        Clean up partial downloads after cancellation.

        Removes files with _download_ prefix that weren't fully processed.
        These are incomplete archive downloads that can't be resumed.

        Args:
            tasks: List of DownloadTask objects that were being processed

        Returns:
            Number of files cleaned up
        """
        cleaned = 0
        for task in tasks:
            # Only archives have the _download_ prefix
            if task.is_archive and task.local_path.name.startswith("_download_"):
                # Check both the original path and the renamed path (without prefix)
                paths_to_check = [
                    task.local_path,  # _download_archive.zip
                    task.local_path.parent / task.local_path.name[10:],  # archive.zip (renamed but not extracted)
                ]
                for path in paths_to_check:
                    if path.exists():
                        try:
                            path.unlink()
                            cleaned += 1
                        except Exception:
                            pass  # Non-fatal
        return cleaned

    async def _download_many_async(
        self,
        tasks: List[DownloadTask],
        progress: Optional[FolderProgress],
        progress_callback: Optional[Callable[[DownloadResult], None]],
    ) -> Tuple[int, int, List[DownloadTask], int, bool]:
        """
        Internal async implementation of download_many.

        Returns:
            Tuple of (downloaded_count, error_count, retryable_tasks, auth_failures, cancelled)
        """
        downloaded = 0
        errors = 0
        auth_failures = 0  # Track 401/auth errors separately
        retryable_tasks: List[DownloadTask] = []
        cancelled = False
        loop = asyncio.get_event_loop()

        # Reduce concurrency for large files to prevent bandwidth saturation
        large_files = [t for t in tasks if t.size > LARGE_FILE_THRESHOLD]
        if large_files:
            effective_workers = min(self.max_workers, 8)
        else:
            effective_workers = self.max_workers

        semaphore = asyncio.Semaphore(effective_workers)

        # Limit extraction concurrency to prevent "too many open files" errors
        extract_semaphore = threading.Semaphore(2)

        def process_archive_limited(task: DownloadTask) -> Tuple[bool, str]:
            """Wrapper to limit concurrent extractions."""
            with extract_semaphore:
                return self.process_archive(task)

        # Create SSL context using certifi's CA bundle
        # This is required for PyInstaller builds which don't have system certs
        ssl_context = ssl.create_default_context(cafile=get_certifi_path())

        # Create connector with connection pooling scaled to effective workers
        connector = aiohttp.TCPConnector(
            limit=effective_workers * 2,  # Total connection pool
            limit_per_host=effective_workers,  # All to Google Drive
            ttl_dns_cache=300,
            keepalive_timeout=30,  # Reuse connections
            ssl=ssl_context,
        )

        async with aiohttp.ClientSession(timeout=self.timeout, connector=connector) as session:
            # Create all download coroutines as tasks
            pending = {
                asyncio.create_task(
                    self._download_file_async(session, task, semaphore, progress),
                    name=str(task.local_path)
                ): task
                for task in tasks
            }

            try:
                while pending:
                    # Check for cancellation
                    if progress and progress.cancelled:
                        cancelled = True
                        for t in pending:
                            t.cancel()
                        break

                    # Wait for the next task to complete
                    done, _ = await asyncio.wait(
                        pending.keys(),
                        timeout=0.1,  # Short timeout to check cancellation
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    for async_task in done:
                        task = pending.pop(async_task)

                        try:
                            result = async_task.result()
                        except asyncio.CancelledError:
                            continue
                        except Exception as e:
                            errors += 1
                            if progress:
                                progress.file_completed(task.local_path)
                            continue

                        if result.success:
                            # Process archive if needed (run in executor to not block)
                            # Uses extract_semaphore to limit concurrent extractions
                            if task.is_archive:
                                archive_success, archive_error = await loop.run_in_executor(
                                    None, process_archive_limited, task
                                )
                                if not archive_success:
                                    errors += 1
                                    if progress:
                                        progress.file_completed(task.local_path)
                                        progress.write(f"  ERR: {task.local_path.parent.name} - {archive_error}")
                                    continue

                                # Report archive completion
                                if progress:
                                    # Get display name (strip _download_ prefix)
                                    archive_name = task.local_path.name
                                    if archive_name.startswith("_download_"):
                                        archive_name = archive_name[10:]
                                    progress.archive_completed(task.local_path, archive_name)

                            downloaded += 1
                            if progress:
                                # For non-archive files, check if folder is complete
                                if not task.is_archive:
                                    completed_info = progress.file_completed(result.file_path)
                                    if completed_info:
                                        folder_name, is_chart = completed_info
                                        progress.print_folder_complete(folder_name, is_chart)
                                else:
                                    # Just mark file as completed (archive already reported)
                                    progress.file_completed(result.file_path)
                        else:
                            errors += 1
                            # Track auth failures separately for better user guidance
                            if "auth" in result.message.lower() or "401" in result.message:
                                auth_failures += 1
                            # Track retryable failures for later retry
                            if result.retryable:
                                retryable_tasks.append(task)
                            if progress:
                                progress.file_completed(result.file_path)
                                progress.write(f"  {result.message}")

                        if progress_callback:
                            progress_callback(result)

            except asyncio.CancelledError:
                cancelled = True
                for t in pending:
                    t.cancel()

        return downloaded, errors, retryable_tasks, auth_failures, cancelled

    def download_many(
        self,
        tasks: List[DownloadTask],
        progress_callback: Optional[Callable[[DownloadResult], None]] = None,
        show_progress: bool = True,
    ) -> Tuple[int, int, int, int, bool]:
        """
        Download multiple files concurrently using asyncio.

        Args:
            tasks: List of DownloadTask objects
            progress_callback: Optional callback for each completed download
            show_progress: Whether to show progress

        Returns:
            Tuple of (downloaded_count, skipped_count, error_count, rate_limited_count, cancelled)
        """
        if not tasks:
            return 0, 0, 0, 0, False

        progress = None
        if show_progress:
            progress = FolderProgress(total_files=len(tasks), total_folders=0)
            progress.register_folders(tasks)
            print(f"  Downloading {len(tasks)} files across {progress.total_charts} charts...")
            print(f"  (max {self.max_workers} concurrent downloads, press ESC to cancel)")
            print()

        # Set up Ctrl+C handler for cancellation
        original_handler = None

        def handle_cancel():
            if progress and not progress.cancelled:
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

        auth_failures = 0
        try:
            # Run the async download
            downloaded, errors, retryable, auth_failures, cancelled = asyncio.run(
                self._download_many_async(tasks, progress, progress_callback)
            )
            rate_limited = len(retryable)
            permanent_errors = errors - rate_limited
        except KeyboardInterrupt:
            cancelled = True
            downloaded = 0
            permanent_errors = 0
            rate_limited = 0
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
                    print(f"  Cancelled. Downloaded {downloaded} files ({progress.completed_charts} complete charts).")
                    # Clean up partial downloads (files with _download_ prefix)
                    cleaned = self._cleanup_partial_downloads(tasks)
                    if cleaned > 0:
                        print(f"  Cleaned up {cleaned} partial download(s).")

        # Print helpful guidance for auth failures only if no retries pending
        # If we have retryable tasks, wait until after retries to show guidance
        if auth_failures > 0 and rate_limited == 0:
            print()
            print(f"  ⚠ {auth_failures} files failed due to access restrictions.")
            print()
            print("  These files aren't shared publicly. To fix this:")
            print()
            print("    1. Open the folder link in your browser while signed in to Google")
            print("    2. Right-click the folder → 'Add shortcut to Drive' → select My Drive")
            print()
            print("  This adds the folder to your Drive, which grants your account access.")
            print("  Then try downloading again.")
            print()
            print("  If that doesn't work, the folder may have restricted sharing settings.")
            print("  Ask the owner to set sharing to 'Anyone with the link' for public access.")
            print()

        return downloaded, 0, permanent_errors, rate_limited, cancelled

    def filter_existing(
        self,
        files: List[dict],
        local_base: Path,
    ) -> Tuple[List[DownloadTask], int, List[str]]:
        """
        Filter files that already exist locally.

        For regular files: check if exists with matching size.
        For archives: check if check.txt has matching MD5.

        Args:
            files: List of file dicts with id, path, size keys
            local_base: Base path for local files

        Returns:
            Tuple of (tasks_to_download, skipped_count, long_paths)
            long_paths: List of paths that exceed Windows MAX_PATH (only on Windows)
        """
        to_download = []
        skipped = 0
        long_paths = []
        is_windows = os.name == 'nt'

        for f in files:
            # Sanitize path for Windows-illegal characters (*, ?, ", <, >, |, :)
            file_path = sanitize_path(f["path"])
            file_name = file_path.split("/")[-1] if "/" in file_path else file_path
            file_size = f.get("size", 0)
            file_md5 = f.get("md5", "")

            # Skip Google Docs/Sheets (no MD5 AND no file extension = can't download as binary)
            # Regular files have MD5s; even extensionless files like _rb3con have MD5s
            if not file_md5 and "." not in file_name:
                skipped += 1
                continue

            if is_archive_file(file_name):
                # Archive file: check MD5 in check.txt
                # The chart folder is the parent of where the archive would be
                local_path = local_base / file_path
                chart_folder = local_path.parent

                # Check for long path on Windows
                download_path = chart_folder / f"_download_{file_name}"
                if is_windows and len(str(download_path)) >= WINDOWS_MAX_PATH:
                    long_paths.append(file_path)
                    continue

                stored_md5 = read_checksum(chart_folder, archive_name=file_name)
                if stored_md5 and stored_md5 == file_md5:
                    # Already extracted with matching checksum
                    skipped += 1
                else:
                    # Need to download and extract
                    # Download to temp location within chart folder
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

                # Skip video files if delete_videos is enabled
                if self.delete_videos and Path(file_name).suffix.lower() in VIDEO_EXTENSIONS:
                    skipped += 1
                    continue

                # Check for long path on Windows
                if is_windows and len(str(local_path)) >= WINDOWS_MAX_PATH:
                    long_paths.append(file_path)
                    continue

                if file_exists_with_size(local_path, file_size):
                    skipped += 1
                else:
                    to_download.append(DownloadTask(
                        file_id=f["id"],
                        local_path=local_path,
                        size=file_size,
                        md5=file_md5,
                    ))

        return to_download, skipped, long_paths
