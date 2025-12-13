"""
Drive-related utilities for DM Chart Sync.
"""

import re


def parse_drive_folder_url(url_or_id: str) -> tuple[str | None, str | None]:
    """
    Extract Google Drive folder ID from a URL or raw ID.

    Supports formats:
    - https://drive.google.com/drive/folders/FOLDER_ID
    - https://drive.google.com/drive/folders/FOLDER_ID?usp=sharing
    - https://drive.google.com/drive/u/0/folders/FOLDER_ID
    - Raw folder ID (alphanumeric with - and _)

    Args:
        url_or_id: URL or folder ID string

    Returns:
        Tuple of (folder_id, error_message)
        - (folder_id, None) if valid
        - (None, error_message) if invalid
    """
    url_or_id = url_or_id.strip()

    # Check if it's a Google Drive file link (not a folder)
    file_pattern = r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"
    if re.search(file_pattern, url_or_id):
        return None, "That's a file link, not a folder link"

    # Pattern for folder ID in URL path
    folder_pattern = r"drive\.google\.com/drive(?:/u/\d+)?/folders/([a-zA-Z0-9_-]+)"
    match = re.search(folder_pattern, url_or_id)
    if match:
        return match.group(1), None

    # Check if it's a raw folder ID (alphanumeric with - and _, typically 10+ chars)
    raw_id_pattern = r"^[a-zA-Z0-9_-]{10,}$"
    if re.match(raw_id_pattern, url_or_id):
        return url_or_id, None

    # Check if it looks like a Google Drive URL but wrong format
    if "drive.google.com" in url_or_id:
        return None, "Unrecognized Google Drive URL format"

    return None, "Not a Google Drive URL"
