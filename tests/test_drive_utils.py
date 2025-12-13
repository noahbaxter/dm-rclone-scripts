"""
Tests for drive utilities.

Tests parse_drive_folder_url() - URL parsing for Google Drive folder links.
"""

import pytest

from src.drive.utils import parse_drive_folder_url


class TestParseDriveFolderUrl:
    """Tests for parse_drive_folder_url()."""

    def test_standard_folder_url(self):
        """Standard Google Drive folder URL."""
        url = "https://drive.google.com/drive/folders/1ABC123def456789"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id == "1ABC123def456789"
        assert error is None

    def test_url_with_user_prefix(self):
        """URL with /u/0/ user selector."""
        url = "https://drive.google.com/drive/u/0/folders/1ABC123def456789"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id == "1ABC123def456789"
        assert error is None

    def test_url_with_user_prefix_other_number(self):
        """URL with /u/1/ or /u/2/ user selector."""
        url = "https://drive.google.com/drive/u/2/folders/1ABC123def456789"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id == "1ABC123def456789"
        assert error is None

    def test_url_with_sharing_param(self):
        """URL with ?usp=sharing query param."""
        url = "https://drive.google.com/drive/folders/1ABC123def456789?usp=sharing"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id == "1ABC123def456789"
        assert error is None

    def test_url_with_multiple_query_params(self):
        """URL with multiple query parameters."""
        url = "https://drive.google.com/drive/folders/1ABC123def456789?usp=sharing&resourcekey=abc"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id == "1ABC123def456789"
        assert error is None

    def test_raw_folder_id(self):
        """Raw folder ID without URL."""
        folder_id, error = parse_drive_folder_url("1ABC123def456_-xyz")
        assert folder_id == "1ABC123def456_-xyz"
        assert error is None

    def test_raw_folder_id_with_dashes_and_underscores(self):
        """Raw folder ID containing dashes and underscores."""
        folder_id, error = parse_drive_folder_url("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf")
        assert folder_id == "1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf"
        assert error is None

    def test_whitespace_trimmed(self):
        """Leading/trailing whitespace should be trimmed."""
        folder_id, error = parse_drive_folder_url("  1ABC123def456789  ")
        assert folder_id == "1ABC123def456789"
        assert error is None

    def test_whitespace_trimmed_from_url(self):
        """Whitespace trimmed from full URL."""
        url = "  https://drive.google.com/drive/folders/1ABC123def456789  "
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id == "1ABC123def456789"
        assert error is None


class TestParseDriveFolderUrlErrors:
    """Tests for error cases in parse_drive_folder_url()."""

    def test_file_url_rejected(self):
        """File URLs should be rejected with helpful message."""
        url = "https://drive.google.com/file/d/1ABC123def456/view"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id is None
        assert error is not None
        assert "file" in error.lower()

    def test_file_url_with_usp_rejected(self):
        """File URL with query params rejected."""
        url = "https://drive.google.com/file/d/1ABC123def456/view?usp=sharing"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id is None
        assert "file" in error.lower()

    def test_open_url_format_rejected(self):
        """Old ?id= format URL rejected."""
        url = "https://drive.google.com/open?id=1ABC123"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id is None
        assert error is not None

    def test_drive_url_wrong_path_rejected(self):
        """Drive URL with wrong path rejected."""
        url = "https://drive.google.com/drive/my-drive"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id is None
        assert error is not None

    def test_non_drive_url_rejected(self):
        """Non-Google-Drive URLs rejected."""
        url = "https://example.com/folder/123"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id is None
        assert error is not None

    def test_dropbox_url_rejected(self):
        """Dropbox URLs rejected."""
        url = "https://www.dropbox.com/sh/abc123/folder"
        folder_id, error = parse_drive_folder_url(url)
        assert folder_id is None
        assert error is not None

    def test_short_string_rejected(self):
        """Strings too short to be folder IDs rejected."""
        folder_id, error = parse_drive_folder_url("abc")
        assert folder_id is None
        assert error is not None

    def test_empty_string_rejected(self):
        """Empty string rejected."""
        folder_id, error = parse_drive_folder_url("")
        assert folder_id is None
        assert error is not None

    def test_whitespace_only_rejected(self):
        """Whitespace-only string rejected."""
        folder_id, error = parse_drive_folder_url("   ")
        assert folder_id is None
        assert error is not None

    def test_special_chars_rejected(self):
        """Strings with special characters rejected as raw IDs."""
        folder_id, error = parse_drive_folder_url("abc!@#$%^&*()")
        assert folder_id is None
        assert error is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
