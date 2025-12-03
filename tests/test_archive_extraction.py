"""
Minimal, targeted tests for archive extraction encoding handling.

These tests verify the specific fix for non-UTF-8 filenames in archives.
Each test validates real behavior that would break if the fix is reverted.
"""

import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.sync.downloader import (
    _run_extract_cmd,
    extract_archive,
    UNIVERSAL_CLI_TOOL,
)


class TestEncodingHandling:
    """
    Critical tests for the encoding fix.

    These tests WILL FAIL if someone reverts to `text=True` in subprocess calls.
    """

    def test_non_utf8_stdout_does_not_crash(self):
        """
        Verify that non-UTF-8 bytes in CLI output don't crash extraction.

        This is THE critical test. The byte 0xfc is:
        - Valid in Windows-1252 (represents ü)
        - INVALID in UTF-8

        Before the fix: UnicodeDecodeError crash
        After the fix: Graceful handling with replacement char
        """
        # Command outputs raw byte 0xfc which is invalid UTF-8
        cmd = ["python3", "-c", "import sys; sys.stdout.buffer.write(b'File: Test\\xfcr.txt\\n')"]

        # This MUST NOT raise UnicodeDecodeError
        success, error = _run_extract_cmd(cmd, "test")

        assert success is True
        assert error == ""

    def test_non_utf8_stderr_does_not_crash(self):
        """
        Verify that non-UTF-8 bytes in CLI stderr don't crash extraction.

        CLI tools may output filenames to stderr when reporting errors.
        """
        # Command outputs 0xfc to stderr and exits with error
        cmd = ["python3", "-c", "import sys; sys.stderr.buffer.write(b'Error: \\xfcmlaut\\n'); sys.exit(1)"]

        # This MUST NOT raise UnicodeDecodeError
        success, error = _run_extract_cmd(cmd, "test")

        assert success is False
        assert "test failed:" in error
        # The invalid byte should be replaced, not cause a crash


class TestFallbackBehavior:
    """Tests for the library-to-CLI fallback mechanism."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_cli_fallback_on_library_unicode_error(self, temp_dir):
        """
        Verify that UnicodeDecodeError in library triggers CLI fallback.

        This tests the fallback path that saves extraction when Python
        libraries fail on encoding issues.
        """
        # Create a real ZIP file
        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("test.txt", "content")

        dest = temp_dir / "extracted"
        dest.mkdir()

        # Mock zipfile to simulate encoding error (as if archive has bad filename)
        with patch('zipfile.ZipFile') as mock_zip:
            mock_zip.side_effect = UnicodeDecodeError('utf-8', b'\xfc', 0, 1, 'invalid byte')

            success, error = extract_archive(zip_path, dest)

            # If CLI tools available, should succeed via fallback
            # If no CLI tools, should get helpful error message
            if UNIVERSAL_CLI_TOOL:
                assert success is True, f"CLI fallback should work, got: {error}"
            else:
                assert "install" in error.lower(), "Should provide install guidance"

    def test_basic_zip_extraction_still_works(self, temp_dir):
        """Sanity check that normal extraction isn't broken."""
        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("hello.txt", "world")

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(zip_path, dest)

        assert success is True
        assert (dest / "hello.txt").read_text() == "world"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
