"""
Tests for archive extraction.

Tests Python library extraction for ZIP, 7z, and RAR formats.
"""

import io
import os
import tempfile
import zipfile
from pathlib import Path

import py7zr
import pytest

from src.sync.downloader import extract_archive

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Fake chart files for testing
FAKE_CHART_FILES = {
    "song.ini": "[song]\nname=Test Song\nartist=Test Artist\n",
    "notes.mid": b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x00\x80",  # Minimal MIDI header
    "song.ogg": b"OggS\x00\x02" + b"\x00" * 20,  # Minimal OGG header stub
}


class TestArchiveFormats:
    """Test extraction of different archive formats with chart-like content."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def _create_zip(self, path: Path, folder_name: str = "Test Chart"):
        """Create a ZIP archive with fake chart files."""
        with zipfile.ZipFile(path, 'w') as zf:
            for name, content in FAKE_CHART_FILES.items():
                if isinstance(content, bytes):
                    zf.writestr(f"{folder_name}/{name}", content)
                else:
                    zf.writestr(f"{folder_name}/{name}", content)

    def _create_7z(self, path: Path, folder_name: str = "Test Chart"):
        """Create a 7z archive with fake chart files."""
        with py7zr.SevenZipFile(path, 'w') as sz:
            for name, content in FAKE_CHART_FILES.items():
                data = content if isinstance(content, bytes) else content.encode()
                sz.writef(io.BytesIO(data), f"{folder_name}/{name}")

    def _verify_chart_extracted(self, dest: Path, folder_name: str = "Test Chart"):
        """Verify chart files were extracted correctly."""
        chart_dir = dest / folder_name
        assert chart_dir.exists(), f"Chart folder not found: {chart_dir}"
        assert (chart_dir / "song.ini").exists(), "song.ini not extracted"
        assert (chart_dir / "notes.mid").exists(), "notes.mid not extracted"
        assert (chart_dir / "song.ogg").exists(), "song.ogg not extracted"
        # Verify content
        ini_content = (chart_dir / "song.ini").read_text()
        assert "Test Song" in ini_content

    def test_zip_chart_extraction(self, temp_dir):
        """ZIP archive with chart files extracts correctly."""
        zip_path = temp_dir / "chart.zip"
        self._create_zip(zip_path)

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(zip_path, dest)

        assert success, f"ZIP extraction failed: {error}"
        self._verify_chart_extracted(dest)

    def test_7z_chart_extraction(self, temp_dir):
        """7z archive with chart files extracts correctly."""
        sz_path = temp_dir / "chart.7z"
        self._create_7z(sz_path)

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(sz_path, dest)

        assert success, f"7z extraction failed: {error}"
        self._verify_chart_extracted(dest)

    @pytest.mark.skipif(
        not (FIXTURES_DIR / "test_chart.rar").exists(),
        reason="RAR fixture not found - create with: rar a tests/fixtures/test_chart.rar 'Test Chart/'"
    )
    def test_rar_chart_extraction(self, temp_dir):
        """RAR archive with chart files extracts correctly."""
        rar_path = FIXTURES_DIR / "test_chart.rar"

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(rar_path, dest)

        assert success, f"RAR extraction failed: {error}"
        self._verify_chart_extracted(dest)


class TestArchiveErrorHandling:
    """Tests for graceful failure on bad archives."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_corrupt_zip_returns_error(self, temp_dir):
        """Corrupt ZIP should fail gracefully, not crash."""
        corrupt_zip = temp_dir / "corrupt.zip"
        corrupt_zip.write_bytes(b"PK\x03\x04" + b"\x00" * 100)  # ZIP header + garbage

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(corrupt_zip, dest)

        assert success is False
        assert error != ""  # Should have error message

    def test_corrupt_7z_returns_error(self, temp_dir):
        """Corrupt 7z should fail gracefully, not crash."""
        corrupt_7z = temp_dir / "corrupt.7z"
        corrupt_7z.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 100)  # 7z header + garbage

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(corrupt_7z, dest)

        assert success is False
        assert error != ""

    def test_unsupported_extension_returns_error(self, temp_dir):
        """Unknown extension should return helpful error."""
        fake_archive = temp_dir / "archive.tar.gz"
        fake_archive.write_bytes(b"fake content")

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(fake_archive, dest)

        assert success is False
        assert "Unsupported" in error or "unsupported" in error.lower()



class TestArchiveEdgeCases:
    """Edge cases that occur in real chart archives."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_long_path_extraction(self, temp_dir):
        """Archive with long nested path extracts correctly.

        This is the critical test for the Windows long path issue.
        Python libraries handle file I/O directly, bypassing the 260 char
        Windows API limit that CLI tools hit.
        """
        zip_path = temp_dir / "long_path.zip"
        # Create a path that would exceed 260 chars on Windows
        # Each segment is ~50 chars, 6 levels = ~300 chars total
        segments = ["This_Is_A_Very_Long_Folder_Name_For_Testing_Paths"] * 6
        long_path = "/".join(segments)

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr(f"{long_path}/song.ini", "[song]\nname=Long Path Test\n")
            zf.writestr(f"{long_path}/notes.mid", b"MThd")

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(zip_path, dest)

        assert success, f"Long path extraction failed: {error}"
        extracted_path = dest / long_path.replace("/", os.sep)
        assert extracted_path.exists(), f"Long path folder not found: {extracted_path}"
        assert (extracted_path / "song.ini").exists()

    def test_unicode_folder_name_zip(self, temp_dir):
        """ZIP with unicode folder name extracts correctly."""
        zip_path = temp_dir / "unicode_test.zip"
        folder_name = "日本語チャート"

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr(f"{folder_name}/song.ini", "[song]\nname=Test\n")
            zf.writestr(f"{folder_name}/notes.mid", b"MThd")

        dest = temp_dir / "extracted"
        dest.mkdir()

        success, error = extract_archive(zip_path, dest)

        assert success, f"Unicode extraction failed: {error}"
        assert (dest / folder_name).exists()
        assert (dest / folder_name / "song.ini").exists()

class TestProcessArchiveIntegration:
    """
    End-to-end integration tests for process_archive → sync_state → scan_local_files.

    This is the critical test that catches cross-platform path bugs:
    - process_archive() extracts files and stores paths in sync_state
    - scan_local_files() scans the same directory
    - If path formats don't match, purge detection breaks

    On Windows, this test will fail if we regress to using str(path.relative_to())
    instead of path.as_posix() in scan_extracted_files().
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def _create_test_archive(self, archive_path: Path, folder_structure: dict):
        """Create a ZIP archive with nested folder structure."""
        with zipfile.ZipFile(archive_path, 'w') as zf:
            for rel_path, content in folder_structure.items():
                if isinstance(content, bytes):
                    zf.writestr(rel_path, content)
                else:
                    zf.writestr(rel_path, content)

    def test_process_archive_paths_match_local_scan(self, temp_dir):
        """
        THE critical integration test: paths stored by process_archive must
        match paths returned by scan_local_files for the same files.

        This is the exact bug scenario - if process_archive stores backslash
        paths on Windows but scan_local_files returns forward-slash paths,
        the comparison fails and files get incorrectly flagged for purge.
        """
        from src.sync.downloader import FileDownloader, DownloadTask
        from src.sync.state import SyncState
        from src.sync.cache import scan_local_files

        # Set up folder structure simulating a drive
        drive_path = temp_dir / "TestDrive" / "Setlist"
        drive_path.mkdir(parents=True)

        # Create archive with nested structure
        archive_path = drive_path / "_download_test_chart.zip"
        self._create_test_archive(archive_path, {
            "Chart Folder/song.ini": "[song]\nname=Test",
            "Chart Folder/notes.mid": b"MThd",
            "Chart Folder/Subfolder/extra.txt": "nested file",
        })

        # Set up sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # Create downloader and process the archive
        downloader = FileDownloader(delete_videos=False)
        task = DownloadTask(
            file_id="test123",
            local_path=archive_path,
            size=archive_path.stat().st_size,
            md5="abc123",
            is_archive=True,
            rel_path="TestDrive/Setlist/test_chart.zip"
        )

        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path="TestDrive/Setlist/test_chart.zip"
        )

        assert success, f"process_archive failed: {error}"

        # Now scan the same directory with scan_local_files
        local_files = scan_local_files(drive_path)

        # Get paths stored in sync_state (under the drive prefix)
        all_synced = sync_state.get_all_files()
        synced_in_setlist = {
            p.replace("TestDrive/Setlist/", "")
            for p in all_synced
            if p.startswith("TestDrive/Setlist/")
        }

        # THE CRITICAL ASSERTION: paths must match exactly
        assert synced_in_setlist == set(local_files.keys()), (
            f"Path mismatch between sync_state and local scan!\n"
            f"sync_state paths: {sorted(synced_in_setlist)}\n"
            f"local_files paths: {sorted(local_files.keys())}\n"
            f"This indicates a cross-platform path separator bug."
        )

        # Verify no backslashes anywhere
        for path in synced_in_setlist:
            assert "\\" not in path, f"Backslash in sync_state: {path}"
        for path in local_files.keys():
            assert "\\" not in path, f"Backslash in local_files: {path}"

    def test_process_archive_with_deep_nesting(self, temp_dir):
        """Test with deeply nested paths - more likely to expose path issues."""
        from src.sync.downloader import FileDownloader, DownloadTask
        from src.sync.state import SyncState
        from src.sync.cache import scan_local_files

        drive_path = temp_dir / "TestDrive" / "Deep"
        drive_path.mkdir(parents=True)

        # Create archive with deep nesting
        archive_path = drive_path / "_download_deep.zip"
        self._create_test_archive(archive_path, {
            "Level1/Level2/Level3/song.ini": "[song]",
            "Level1/Level2/Level3/notes.mid": b"midi",
            "Level1/Level2/other.txt": "file",
            "Level1/root.txt": "root",
        })

        sync_state = SyncState(temp_dir)
        sync_state.load()

        downloader = FileDownloader(delete_videos=False)
        task = DownloadTask(
            file_id="deep",
            local_path=archive_path,
            size=archive_path.stat().st_size,
            md5="deep123",
            is_archive=True,
            rel_path="TestDrive/Deep/deep.zip"
        )

        success, error, _ = downloader.process_archive(
            task, sync_state, archive_rel_path="TestDrive/Deep/deep.zip"
        )

        assert success, f"Deep nesting extraction failed: {error}"

        # Compare paths
        local_files = scan_local_files(drive_path)
        all_synced = sync_state.get_all_files()
        synced_here = {
            p.replace("TestDrive/Deep/", "")
            for p in all_synced
            if p.startswith("TestDrive/Deep/")
        }

        assert synced_here == set(local_files.keys()), (
            f"Deep nesting path mismatch!\n"
            f"sync_state: {sorted(synced_here)}\n"
            f"local: {sorted(local_files.keys())}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
