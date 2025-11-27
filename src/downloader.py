"""
File downloader for DM Chart Sync.

Handles parallel file downloads with progress tracking and retries.
"""

import threading
from pathlib import Path
from typing import Callable, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests
from tqdm import tqdm


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


class FileDownloader:
    """
    Parallel file downloader with progress tracking.

    Uses direct Google Drive download URLs instead of the API
    to avoid authentication requirements for public files.
    """

    DOWNLOAD_URL_TEMPLATE = "https://drive.google.com/uc?export=download&id={file_id}&confirm=1"

    def __init__(
        self,
        max_workers: int = 8,
        max_retries: int = 3,
        timeout: Tuple[int, int] = (10, 60),
        chunk_size: int = 32768,
    ):
        """
        Initialize the downloader.

        Args:
            max_workers: Number of parallel download threads
            max_retries: Number of retry attempts per file
            timeout: Request timeout (connect, read)
            chunk_size: Download chunk size in bytes
        """
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.timeout = timeout
        self.chunk_size = chunk_size
        self._print_lock = threading.Lock()

    def download_file(self, task: DownloadTask) -> DownloadResult:
        """
        Download a single file with retries.

        Args:
            task: DownloadTask with file info

        Returns:
            DownloadResult with success status and message
        """
        url = self.DOWNLOAD_URL_TEMPLATE.format(file_id=task.file_id)

        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    stream=True,
                    allow_redirects=True,
                    timeout=self.timeout
                )
                response.raise_for_status()

                # Check if we got HTML instead of the file (auth required)
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type:
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
                    return DownloadResult(
                        success=False,
                        file_path=task.local_path,
                        message=f"SKIP (access denied): {task.local_path.name}",
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

    def download_many(
        self,
        tasks: List[DownloadTask],
        progress_callback: Optional[Callable[[DownloadResult], None]] = None,
        show_progress: bool = True,
    ) -> Tuple[int, int, int]:
        """
        Download multiple files in parallel.

        Args:
            tasks: List of DownloadTask objects
            progress_callback: Optional callback for each completed download
            show_progress: Whether to show tqdm progress bar

        Returns:
            Tuple of (downloaded_count, skipped_count, error_count)
        """
        if not tasks:
            return 0, 0, 0

        downloaded = 0
        errors = 0

        pbar = None
        if show_progress:
            pbar = tqdm(total=len(tasks), desc="  Downloading", unit="file")

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self.download_file, task): task
                    for task in tasks
                }

                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        result = future.result()

                        if pbar:
                            with self._print_lock:
                                pbar.set_postfix_str(task.local_path.name[:30])
                                pbar.update(1)

                        if result.success:
                            downloaded += 1
                        else:
                            errors += 1
                            if pbar:
                                tqdm.write(f"  {result.message}")

                        if progress_callback:
                            progress_callback(result)

                    except Exception as e:
                        errors += 1
                        if pbar:
                            with self._print_lock:
                                pbar.update(1)
                                tqdm.write(f"  ERR: {task.local_path.name} - {e}")

        finally:
            if pbar:
                pbar.close()

        return downloaded, 0, errors

    @staticmethod
    def filter_existing(
        files: List[dict],
        local_base: Path,
    ) -> Tuple[List[DownloadTask], int]:
        """
        Filter files that already exist locally with matching size.

        Args:
            files: List of file dicts with id, path, size keys
            local_base: Base path for local files

        Returns:
            Tuple of (tasks_to_download, skipped_count)
        """
        to_download = []
        skipped = 0

        for f in files:
            local_path = local_base / f["path"]
            file_size = f.get("size", 0)

            if local_path.exists() and local_path.stat().st_size == file_size:
                skipped += 1
            else:
                to_download.append(DownloadTask(
                    file_id=f["id"],
                    local_path=local_path,
                    size=file_size,
                    md5=f.get("md5", ""),
                ))

        return to_download, skipped
