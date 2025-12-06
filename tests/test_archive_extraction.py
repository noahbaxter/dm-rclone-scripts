"""
Minimal, targeted tests for archive extraction encoding handling.

These tests verify the specific fix for non-UTF-8 filenames in archives.
Each test validates real behavior that would break if the fix is reverted.
"""

import os
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


def _create_rar_archive(rar_path: Path, files: dict) -> bool:
    """
    Create a RAR archive using WinRAR CLI.

    Args:
        rar_path: Path where the RAR file should be created
        files: Dict mapping relative paths to content (str or bytes)

    Returns:
        True if RAR was created successfully, False otherwise
    """
    import subprocess
    import shutil

    rar_exe = shutil.which("rar")
    if not rar_exe:
        return False

    with tempfile.TemporaryDirectory() as staging_dir:
        staging = Path(staging_dir)

        for rel_path, content in files.items():
            file_path = staging / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                file_path.write_bytes(content)
            else:
                file_path.write_text(content)

        result = subprocess.run(
            [rar_exe, "a", "-ep1", "-r", str(rar_path), "*"],
            cwd=staging,
            capture_output=True,
        )
        return result.returncode == 0


def _has_rar_tools() -> bool:
    """Check if RAR creation and extraction tools are available."""
    import shutil
    return shutil.which("rar") is not None


@pytest.mark.skipif(os.name != 'nt', reason="Windows-specific long path test")
@pytest.mark.skipif(not _has_rar_tools(), reason="WinRAR CLI not available")
class TestLongPathHandling:
    """Tests for long path handling on Windows with RAR files."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_rar_extraction_to_long_path_succeeds(self, temp_dir):
        """
        Verify RAR extraction works when destination path is very long.

        CLI tools like unrar don't support Windows long paths even with
        LongPathsEnabled. The fix extracts to a short temp path first,
        then moves contents to the final destination.
        """
        rar_path = temp_dir / "test.rar"
        nested_folder = "Artist Name - Song Title (Some Long Qualifier)"
        files = {f"{nested_folder}/file.txt": "content"}

        assert _create_rar_archive(rar_path, files), "Failed to create RAR archive"

        # Create a long destination path (>100 chars to trigger temp extraction)
        long_folder_name = "A" * 50
        dest = temp_dir / long_folder_name / long_folder_name / "extracted"
        dest.mkdir(parents=True)

        assert len(str(dest)) > 100, f"Dest path should be >100 chars: {len(str(dest))}"

        success, error = extract_archive(rar_path, dest)

        assert success is True, f"Extraction failed: {error}"
        extracted_file = dest / nested_folder / "file.txt"
        assert extracted_file.exists(), f"Expected file at {extracted_file}"
        assert extracted_file.read_text() == "content"

    def test_rar_extraction_with_long_inner_folder_name(self, temp_dir):
        """
        Verify RAR extraction works with long filenames inside archive.

        This is the exact scenario that caused the original bug with unrar.exe.
        """
        rar_path = temp_dir / "test.rar"
        inner_folder = "Biffy Clyro - God Only Knows (The Beach Boys Cover) (MTV Unplugged)"
        files = {f"{inner_folder}/notes.mid": b"MThd"}

        assert _create_rar_archive(rar_path, files), "Failed to create RAR archive"

        dest_folder = "Sync Charts - Misc - Joshwantsmaccas - Some Extra Padding Here"
        dest = temp_dir / dest_folder / "chart_folder"
        dest.mkdir(parents=True)

        success, error = extract_archive(rar_path, dest)

        assert success is True, f"Extraction failed: {error}"
        extracted_file = dest / inner_folder / "notes.mid"
        assert extracted_file.exists(), f"Expected file at {extracted_file}"

    def test_short_path_rar_extraction_still_works(self, temp_dir):
        """Verify short paths work correctly with RAR files."""
        rar_path = temp_dir / "test.rar"
        files = {"test.txt": "content"}

        assert _create_rar_archive(rar_path, files), "Failed to create RAR archive"

        dest = temp_dir / "out"
        dest.mkdir()

        success, error = extract_archive(rar_path, dest)

        assert success is True, f"Extraction failed: {error}"
        assert (dest / "test.txt").read_text() == "content"

    def test_zip_extraction_still_works(self, temp_dir):
        """Verify ZIP extraction still works (baseline test)."""
        zip_path = temp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("test.txt", "content")

        dest = temp_dir / "out"
        dest.mkdir()

        success, error = extract_archive(zip_path, dest)

        assert success is True
        assert (dest / "test.txt").read_text() == "content"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
