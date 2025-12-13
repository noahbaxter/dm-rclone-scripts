"""
Core utilities for DM Chart Sync.

Shared constants, paths, file operations, and formatting.
"""

from .constants import (
    CHART_MARKERS,
    CHART_ARCHIVE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    USER_OAUTH_CLIENT_ID,
    USER_OAUTH_CLIENT_SECRET,
    USER_OAUTH_SCOPES,
)

from .paths import (
    get_app_dir,
    get_bundle_dir,
    get_data_dir,
    get_settings_path,
    get_token_path,
    get_manifest_path,
    get_local_manifest_path,
    get_download_path,
    get_drives_config_path,
    get_sync_state_path,
    get_tmp_dir,
    get_extract_tmp_dir,
    cleanup_tmp_dir,
    migrate_legacy_files,
)

from .files import (
    file_exists_with_size,
    find_unexpected_files,
)

from .formatting import (
    format_size,
    format_duration,
    sanitize_filename,
    sanitize_path,
    name_sort_key,
    sort_by_name,
)

from .progress import ProgressTracker

__all__ = [
    # Constants
    "CHART_MARKERS",
    "CHART_ARCHIVE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "USER_OAUTH_CLIENT_ID",
    "USER_OAUTH_CLIENT_SECRET",
    "USER_OAUTH_SCOPES",
    # Paths
    "get_app_dir",
    "get_bundle_dir",
    "get_data_dir",
    "get_settings_path",
    "get_token_path",
    "get_manifest_path",
    "get_local_manifest_path",
    "get_download_path",
    "get_drives_config_path",
    "get_sync_state_path",
    "get_tmp_dir",
    "get_extract_tmp_dir",
    "cleanup_tmp_dir",
    "migrate_legacy_files",
    # Files
    "file_exists_with_size",
    "find_unexpected_files",
    # Formatting
    "format_size",
    "format_duration",
    "sanitize_filename",
    "sanitize_path",
    "name_sort_key",
    "sort_by_name",
    # Progress
    "ProgressTracker",
]
