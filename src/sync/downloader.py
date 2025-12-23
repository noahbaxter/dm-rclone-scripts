"""
File downloader for DM Chart Sync.

Handles parallel file downloads with progress tracking and retries.
Uses asyncio + aiohttp for efficient concurrent downloads.
"""

import asyncio
import os
import ssl
import sys
import signal
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Union
from dataclasses import dataclass

import aiohttp

from ..core.constants import VIDEO_EXTENSIONS
from ..core.formatting import extract_path_context, format_download_name
from ..core.paths import get_extract_tmp_dir, get_certifi_ssl_context
from .extractor import extract_archive, get_folder_size, delete_video_files, scan_extracted_files
from .download_planner import DownloadTask
from .state import SyncState
from ..ui.primitives.esc_monitor import EscMonitor
from ..ui.widgets import FolderProgress, display

# Large file threshold for reducing download concurrency (500MB)
LARGE_FILE_THRESHOLD = 500_000_000

# Progress tracking thresholds
PROGRESS_TRACK_MIN_SIZE = 512 * 1024  # 512KB - minimum size to show in active downloads
PROGRESS_TRACK_DELAY = 0.5  # Seconds to wait before showing in active downloads
PROGRESS_UPDATE_INTERVAL = 0.3  # Seconds between progress updates


@dataclass
class DownloadResult:
    """Result of a single file download."""
    success: bool
    file_path: Path
    message: str
    bytes_downloaded: int = 0
    retryable: bool = False


class FileDownloader:
    """
    Async file downloader with progress tracking.

    Uses asyncio + aiohttp for efficient concurrent downloads.
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
        self.max_workers = max_workers
        self.max_retries = max_retries
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
        progress_tracker: Optional[FolderProgress] = None,
    ) -> DownloadResult:
        """Download a single file with retries (async)."""
        display_name = format_download_name(task.local_path)

        async with semaphore:
            for attempt in range(self.max_retries):
                try:
                    url = self.DOWNLOAD_URL_TEMPLATE.format(file_id=task.file_id)
                    async with session.get(url, allow_redirects=True) as response:
                        response.raise_for_status()

                        content_type = response.headers.get("content-type", "")
                        if "text/html" in content_type:
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(1.0 * (attempt + 1))
                                continue

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
                                    message=f"SKIP (sign in to bypass virus scan): {display_name}",
                                    retryable=False,
                                )

                        return await self._write_response(response, task, progress_tracker)

                except asyncio.TimeoutError:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    return DownloadResult(
                        success=False,
                        file_path=task.local_path,
                        message=f"ERR (timeout): {display_name}",
                        retryable=True,
                    )

                except aiohttp.ClientResponseError as e:
                    auth_token = self._get_auth_token()
                    if e.status in (401, 403) and auth_token:
                        try:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            api_url = f"{self.API_DOWNLOAD_URL.format(file_id=task.file_id)}&acknowledgeAbuse=true"
                            headers = {"Authorization": f"Bearer {auth_token}"}
                            async with session.get(api_url, headers=headers) as auth_response:
                                auth_response.raise_for_status()
                                return await self._write_response(auth_response, task, progress_tracker)
                        except aiohttp.ClientResponseError as auth_e:
                            if auth_e.status == 403:
                                msg = f"ERR (folder rate limited): {display_name}"
                            elif auth_e.status == 429:
                                msg = f"ERR (rate limited): {display_name}"
                            else:
                                msg = f"ERR (HTTP {auth_e.status}): {display_name}"
                            # Mark as retryable for tracking (reported to user at end)
                            # 403/429 won't retry this session - user should try again later
                            is_rate_limit = auth_e.status in (403, 429)
                            return DownloadResult(
                                success=False,
                                file_path=task.local_path,
                                message=msg,
                                retryable=is_rate_limit,
                            )
                    if e.status == 403:
                        # Folder rate limited - mark for tracking, user should try again later
                        return DownloadResult(
                            success=False,
                            file_path=task.local_path,
                            message=f"ERR (folder rate limited): {display_name}",
                            retryable=True,
                        )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    if 500 <= e.status < 600:
                        return DownloadResult(
                            success=False,
                            file_path=task.local_path,
                            message=f"ERR (HTTP {e.status}): {display_name} [file_id={task.file_id}]",
                            retryable=False,
                        )
                    return DownloadResult(
                        success=False,
                        file_path=task.local_path,
                        message=f"ERR (HTTP {e.status}): {display_name}",
                        retryable=False,
                    )

                except asyncio.CancelledError:
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
        progress_tracker: Optional[FolderProgress] = None,
    ) -> DownloadResult:
        """Write response content to file."""
        task.local_path.parent.mkdir(parents=True, exist_ok=True)

        downloaded_bytes = 0
        content_length = response.content_length or 0

        # Small files: read all at once
        if content_length > 0 and content_length < PROGRESS_TRACK_MIN_SIZE:
            data = await response.read()
            with open(task.local_path, "wb") as f:
                f.write(data)
            downloaded_bytes = len(data)
        else:
            # Large files: stream with progress tracking
            total_size = task.size if task.size > 0 else content_length
            display_name = format_download_name(task.local_path)
            path_context = extract_path_context(task.rel_path)
            is_tracked = False
            download_start = time.time()
            last_update = download_start

            with open(task.local_path, "wb") as f:
                async for chunk in response.content.iter_chunked(self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)

                        if progress_tracker and total_size > PROGRESS_TRACK_MIN_SIZE:
                            now = time.time()
                            elapsed = now - download_start

                            # Register for tracking after delay
                            if not is_tracked and elapsed >= PROGRESS_TRACK_DELAY:
                                progress_tracker.register_active_download(
                                    task.file_id, display_name, path_context, total_size
                                )
                                is_tracked = True

                            # Update progress periodically
                            if is_tracked and now - last_update >= PROGRESS_UPDATE_INTERVAL:
                                last_update = now
                                progress_tracker.update_active_download(task.file_id, downloaded_bytes)

            # Unregister when done
            if is_tracked and progress_tracker:
                progress_tracker.unregister_active_download(task.file_id)

        return DownloadResult(
            success=True,
            file_path=task.local_path,
            message=f"OK: {task.local_path.name}",
            bytes_downloaded=downloaded_bytes,
        )

    def process_archive(self, task: DownloadTask, sync_state=None, archive_rel_path: str = None) -> Tuple[bool, str, dict]:
        """
        Process a downloaded archive: extract to temp, move contents to destination, update sync state.

        Args:
            task: Download task with archive info
            sync_state: SyncState instance to update (optional for backward compat)
            archive_rel_path: Relative path of archive in manifest (e.g., "DriveName/Setlist/archive.7z")

        Returns:
            Tuple of (success, error_message, extracted_files_dict)
        """
        import shutil

        archive_path = task.local_path
        chart_folder = archive_path.parent

        archive_name = archive_path.name.replace("_download_", "", 1)
        archive_stem = Path(archive_name).stem
        archive_size = task.size

        # Rename from _download_ prefix if needed
        if archive_path.name.startswith("_download_"):
            clean_archive_path = chart_folder / archive_name
            try:
                archive_path.rename(clean_archive_path)
                archive_path = clean_archive_path
            except OSError:
                pass

        # Create unique temp folder for extraction
        extract_tmp = get_extract_tmp_dir() / f"{archive_stem}_{id(task)}"
        extract_tmp.mkdir(parents=True, exist_ok=True)

        try:
            # Step 1: Extract to temp folder
            success, error = extract_archive(archive_path, extract_tmp)
            if not success:
                shutil.rmtree(extract_tmp, ignore_errors=True)
                return False, f"Extract failed: {error}", {}

            # Step 2: Delete videos if enabled
            if self.delete_videos:
                delete_video_files(extract_tmp)

            # Step 3: Scan extracted files (relative to temp folder)
            extracted_files = scan_extracted_files(extract_tmp, extract_tmp)

            # Step 4: Move extracted contents to chart_folder
            # Move each top-level item from temp to chart_folder
            for item in extract_tmp.iterdir():
                dest = chart_folder / item.name
                # Remove existing destination if it exists
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))

            # Clean up empty temp folder
            shutil.rmtree(extract_tmp, ignore_errors=True)

            # Step 5: Update sync state if provided
            if sync_state and archive_rel_path:
                sync_state.add_archive(
                    path=archive_rel_path,
                    md5=task.md5,
                    archive_size=archive_size,
                    files=extracted_files
                )
                sync_state.save()

            # Step 6: Delete the archive file
            try:
                archive_path.unlink()
            except Exception:
                pass

            return True, "", extracted_files

        except Exception as e:
            # Cleanup on error
            shutil.rmtree(extract_tmp, ignore_errors=True)
            return False, str(e), {}

    def _cleanup_partial_downloads(self, tasks: List[DownloadTask]) -> int:
        """Clean up partial downloads after cancellation."""
        cleaned = 0
        for task in tasks:
            if task.is_archive and task.local_path.name.startswith("_download_"):
                paths_to_check = [
                    task.local_path,
                    task.local_path.parent / task.local_path.name[10:],
                ]
                for path in paths_to_check:
                    if path.exists():
                        try:
                            path.unlink()
                            cleaned += 1
                        except Exception:
                            pass
        return cleaned

    async def _download_many_async(
        self,
        tasks: List[DownloadTask],
        progress: Optional[FolderProgress],
        progress_callback: Optional[Callable[[DownloadResult], None]],
        sync_state: Optional[SyncState] = None,
    ) -> Tuple[int, int, List[DownloadTask], int, bool]:
        """Internal async implementation of download_many."""
        downloaded = 0
        errors = 0
        auth_failures = 0
        retryable_tasks: List[DownloadTask] = []
        cancelled = False
        loop = asyncio.get_event_loop()

        large_files = [t for t in tasks if t.size > LARGE_FILE_THRESHOLD]
        if large_files:
            effective_workers = min(self.max_workers, 8)
        else:
            effective_workers = self.max_workers

        semaphore = asyncio.Semaphore(effective_workers)
        extract_semaphore = threading.Semaphore(2)

        def process_archive_limited(task: DownloadTask) -> Tuple[bool, str]:
            with extract_semaphore:
                success, error, _ = self.process_archive(task, sync_state, task.rel_path)
                return success, error

        ssl_context = ssl.create_default_context(cafile=get_certifi_ssl_context())

        connector = aiohttp.TCPConnector(
            limit=effective_workers * 2,
            limit_per_host=effective_workers,
            ttl_dns_cache=300,
            keepalive_timeout=30,
            ssl=ssl_context,
        )

        async with aiohttp.ClientSession(timeout=self.timeout, connector=connector) as session:
            pending = {
                asyncio.create_task(
                    self._download_file_async(session, task, semaphore, progress),
                    name=str(task.local_path)
                ): task
                for task in tasks
            }

            try:
                while pending:
                    if progress and progress.cancelled:
                        cancelled = True
                        for t in pending:
                            t.cancel()
                        break

                    done, _ = await asyncio.wait(
                        pending.keys(),
                        timeout=0.1,
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    for async_task in done:
                        task = pending.pop(async_task)

                        try:
                            result = async_task.result()
                        except asyncio.CancelledError:
                            continue
                        except Exception:
                            errors += 1
                            if progress:
                                progress.file_completed(task.local_path)
                            continue

                        path_context = extract_path_context(task.rel_path)

                        if result.success:
                            if task.is_archive:
                                archive_success, archive_error = await loop.run_in_executor(
                                    None, process_archive_limited, task
                                )
                                if not archive_success:
                                    errors += 1
                                    if progress:
                                        progress.file_completed(task.local_path)
                                        progress.print_error(path_context, f"extract: {task.local_path.parent.name} - {archive_error}")
                                    continue

                                if progress:
                                    archive_name = task.local_path.name
                                    if archive_name.startswith("_download_"):
                                        archive_name = archive_name[10:]
                                    progress.archive_completed(task.local_path, archive_name, path_context)

                            downloaded += 1
                            if progress and result.bytes_downloaded > 0:
                                progress.add_downloaded_bytes(result.bytes_downloaded)

                            # Track direct files in sync state
                            if not task.is_archive and sync_state and task.rel_path:
                                sync_state.add_file(task.rel_path, task.size, task.md5)
                                sync_state.save()

                            if progress:
                                if not task.is_archive:
                                    completed_info = progress.file_completed(result.file_path)
                                    if completed_info:
                                        folder_name, is_chart, ctx = completed_info
                                        progress.print_folder_complete(folder_name, is_chart, ctx)
                                else:
                                    progress.file_completed(result.file_path)
                        else:
                            errors += 1
                            if "auth" in result.message.lower() or "401" in result.message:
                                auth_failures += 1
                            if result.retryable:
                                retryable_tasks.append(task)
                            if progress:
                                progress.file_completed(result.file_path)
                                progress.print_error(path_context, result.message)

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
        sync_state: Optional[SyncState] = None,
        drive_name: str = "",
    ) -> Tuple[int, int, int, List[str], bool, int]:
        """Download multiple files concurrently using asyncio.

        Returns:
            Tuple of (downloaded, skipped, errors, rate_limited_file_ids, cancelled, bytes_downloaded)
        """
        if not tasks:
            return 0, 0, 0, [], False, 0

        progress = None
        if show_progress:
            total_bytes = sum(t.size for t in tasks)
            progress = FolderProgress(total_files=len(tasks), total_folders=0)
            progress.register_folders(tasks)
            progress.set_aggregate_totals(len(tasks), total_bytes, drive_name)
            display.download_starting(len(tasks), progress.total_charts, self.max_workers)

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
            pass

        esc_monitor = EscMonitor(on_esc=handle_cancel)
        esc_monitor.start()

        auth_failures = 0
        rate_limited_ids: List[str] = []
        try:
            downloaded, errors, retryable, auth_failures, cancelled = asyncio.run(
                self._download_many_async(tasks, progress, progress_callback, sync_state)
            )
            rate_limited_ids = [t.file_id for t in retryable]
            permanent_errors = errors - len(retryable)
        except KeyboardInterrupt:
            cancelled = True
            downloaded = 0
            permanent_errors = 0
        finally:
            esc_monitor.stop()

            try:
                signal.signal(signal.SIGINT, original_handler or signal.SIG_DFL)
            except Exception:
                pass

            if progress:
                progress.close()
                if cancelled:
                    cleaned = self._cleanup_partial_downloads(tasks)
                    display.download_cancelled(downloaded, progress.completed_charts, cleaned)
                else:
                    progress.print_error_summary()

        if auth_failures > 0 and len(rate_limited_ids) == 0:
            display.auth_expired_warning(auth_failures)

        bytes_downloaded = progress.downloaded_bytes if progress else 0
        return downloaded, 0, permanent_errors, rate_limited_ids, cancelled, bytes_downloaded
