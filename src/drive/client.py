"""
Google Drive API client for DM Chart Sync.

Handles all HTTP interactions with the Google Drive API.
"""

import time
import requests
from typing import Optional
from dataclasses import dataclass


@dataclass
class DriveClientConfig:
    """Configuration for DriveClient."""
    api_key: str
    timeout: int = 60
    max_retries: int = 3


class DriveClient:
    """
    Google Drive API client.

    Handles listing folders, getting file metadata, and API authentication.
    Does NOT handle downloads (see FileDownloader for that).
    """

    API_BASE = "https://www.googleapis.com/drive/v3"
    API_FILES = f"{API_BASE}/files"
    API_CHANGES = f"{API_BASE}/changes"

    def __init__(self, config: DriveClientConfig, auth_token: Optional[str] = None):
        """
        Initialize the Drive client.

        Args:
            config: Client configuration
            auth_token: Optional OAuth token (for Changes API)
        """
        self.config = config
        self.auth_token = auth_token
        self._api_calls = 0

    @property
    def api_calls(self) -> int:
        """Total API calls made by this client."""
        return self._api_calls

    def reset_api_calls(self):
        """Reset the API call counter."""
        self._api_calls = 0

    def _get_headers(self) -> dict:
        """Get request headers."""
        if self.auth_token:
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}

    def _get_params(self, **kwargs) -> dict:
        """Build request params with API key."""
        params = {"key": self.config.api_key, **kwargs}
        return params

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request with retry logic."""
        timeout = kwargs.pop("timeout", self.config.timeout)

        for attempt in range(self.config.max_retries):
            try:
                response = requests.request(method, url, timeout=timeout, **kwargs)
                self._api_calls += 1
                response.raise_for_status()
                return response
            except requests.exceptions.Timeout:
                if attempt < self.config.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except requests.exceptions.HTTPError:
                if attempt < self.config.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

        raise RuntimeError(f"Request failed after {self.config.max_retries} attempts")

    def list_folder(self, folder_id: str) -> list:
        """
        List all files and folders in a Google Drive folder.

        Handles pagination and includes shortcut details for linked folders.

        Args:
            folder_id: Google Drive folder ID

        Returns:
            List of file/folder metadata dicts
        """
        all_items = []
        page_token = None

        while True:
            params = self._get_params(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, size, md5Checksum, modifiedTime, shortcutDetails)",
                pageSize=1000,
                supportsAllDrives="true",
                includeItemsFromAllDrives="true",
            )

            if page_token:
                params["pageToken"] = page_token

            try:
                response = self._request_with_retry(
                    "GET", self.API_FILES,
                    params=params,
                    headers=self._get_headers()
                )
                data = response.json()
            except requests.exceptions.HTTPError as e:
                if hasattr(e, 'response') and e.response.status_code == 403:
                    return []  # Access denied
                raise

            all_items.extend(data.get("files", []))
            page_token = data.get("nextPageToken")

            if not page_token:
                break

        return all_items

    def get_file_metadata(self, file_id: str, fields: str = "id,name,parents") -> Optional[dict]:
        """
        Get metadata for a single file.

        Args:
            file_id: Google Drive file ID
            fields: Comma-separated list of fields to return

        Returns:
            File metadata dict or None if not found
        """
        params = self._get_params(
            fields=fields,
            supportsAllDrives="true",
        )

        try:
            response = self._request_with_retry(
                "GET", f"{self.API_FILES}/{file_id}",
                params=params,
                headers=self._get_headers()
            )
            return response.json()
        except requests.exceptions.HTTPError:
            return None

    def get_changes_start_token(self) -> str:
        """
        Get the starting page token for the Changes API.

        Requires OAuth authentication.

        Returns:
            Start page token string
        """
        if not self.auth_token:
            raise RuntimeError("OAuth token required for Changes API")

        params = {"supportsAllDrives": "true"}
        response = self._request_with_retry(
            "GET", f"{self.API_CHANGES}/startPageToken",
            params=params,
            headers=self._get_headers()
        )
        self._api_calls += 1
        return response.json().get("startPageToken")

    def get_changes(self, page_token: str) -> tuple:
        """
        Get changes since the given page token.

        Requires OAuth authentication.

        Args:
            page_token: Page token from previous call or getStartPageToken

        Returns:
            Tuple of (changes_list, new_page_token)
        """
        if not self.auth_token:
            raise RuntimeError("OAuth token required for Changes API")

        all_changes = []
        current_token = page_token

        while True:
            params = {
                "pageToken": current_token,
                "pageSize": 1000,
                "fields": "nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, size, md5Checksum, modifiedTime, parents, trashed))",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }

            response = self._request_with_retry(
                "GET", self.API_CHANGES,
                params=params,
                headers=self._get_headers()
            )
            data = response.json()

            all_changes.extend(data.get("changes", []))

            if "newStartPageToken" in data:
                return all_changes, data["newStartPageToken"]

            current_token = data.get("nextPageToken")
            if not current_token:
                break

        return all_changes, current_token
