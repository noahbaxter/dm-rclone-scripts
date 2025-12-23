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

    def test_process_archive_nfd_folder_normalized_to_nfc(self, temp_dir):
        """
        Archive with NFD Unicode folder name gets normalized to NFC during extraction.

        This is the "Bôa - Duvet" bug fix: macOS returns NFD from iterdir() but
        the manifest uses NFC. Without normalization, files keep re-downloading
        and purge fails because paths don't match.
        """
        import unicodedata
        from src.sync.downloader import FileDownloader, DownloadTask
        from src.sync.state import SyncState
        from src.sync.cache import scan_local_files

        drive_path = temp_dir / "TestDrive" / "Misc"
        drive_path.mkdir(parents=True)

        # Create archive with NFD folder name (how macOS might create it)
        nfd_folder = unicodedata.normalize("NFD", "Bôa - Duvet")
        nfc_folder = unicodedata.normalize("NFC", "Bôa - Duvet")

        # Verify they're different
        assert nfd_folder != nfc_folder, "Test requires different NFD/NFC representations"

        archive_path = drive_path / "_download_boa.zip"
        self._create_test_archive(archive_path, {
            f"{nfd_folder}/song.ini": "[song]\nname=Duvet",
            f"{nfd_folder}/notes.mid": b"MThd",
        })

        sync_state = SyncState(temp_dir)
        sync_state.load()

        downloader = FileDownloader(delete_videos=False)
        task = DownloadTask(
            file_id="boa",
            local_path=archive_path,
            size=archive_path.stat().st_size,
            md5="boa123",
            is_archive=True,
            rel_path="TestDrive/Misc/boa.zip"
        )

        success, error, _ = downloader.process_archive(
            task, sync_state, archive_rel_path="TestDrive/Misc/boa.zip"
        )

        assert success, f"NFD extraction failed: {error}"

        # The extracted folder should be NFC (normalized), not NFD
        nfc_path = drive_path / nfc_folder
        nfd_path = drive_path / nfd_folder

        # On macOS, the NFC path should exist (or be equivalent)
        # The key assertion: scan_local_files should return NFC paths
        local_files = scan_local_files(drive_path)

        # All paths should use NFC folder name, not NFD
        for path in local_files.keys():
            folder_part = path.split("/")[0]
            assert folder_part == nfc_folder, (
                f"Expected NFC folder '{nfc_folder}', got '{folder_part}' (NFD={nfd_folder})"
            )


    def test_process_archive_flattens_case_mismatched_folder(self, temp_dir):
        """
        Archive with internal folder differing by case from archive name gets flattened.

        This is the "Carol of the Bells" bug: archive "Carol of the Bells.zip" contains
        folder "Carol Of The Bells/". Without flattening, we'd get nested:
            Carol of the Bells/Carol Of The Bells/song.ini
        With flattening, we get:
            Carol of the Bells/song.ini
        """
        from src.sync.downloader import FileDownloader, DownloadTask
        from src.sync.state import SyncState
        from src.sync.cache import scan_local_files

        drive_path = temp_dir / "TestDrive" / "Misc"
        drive_path.mkdir(parents=True)

        # Create archive with case-mismatched internal folder
        # Archive stem: "Carol of the Bells"
        # Internal folder: "Carol Of The Bells" (different case!)
        archive_path = drive_path / "_download_Carol of the Bells.zip"
        self._create_test_archive(archive_path, {
            "Carol Of The Bells/song.ini": "[song]\nname=Carol Test",
            "Carol Of The Bells/notes.mid": b"MThd",
        })

        sync_state = SyncState(temp_dir)
        sync_state.load()

        downloader = FileDownloader(delete_videos=False)
        task = DownloadTask(
            file_id="carol",
            local_path=archive_path,
            size=archive_path.stat().st_size,
            md5="carol123",
            is_archive=True,
            rel_path="TestDrive/Misc/Carol of the Bells.zip"
        )

        success, error, extracted = downloader.process_archive(
            task, sync_state, archive_rel_path="TestDrive/Misc/Carol of the Bells.zip"
        )

        assert success, f"Case mismatch extraction failed: {error}"

        # Files should be FLAT, not nested
        local_files = scan_local_files(drive_path)

        # Should have files directly, not in nested subfolder
        assert "song.ini" in local_files, (
            f"Expected flattened 'song.ini', got: {list(local_files.keys())}"
        )
        assert "notes.mid" in local_files, (
            f"Expected flattened 'notes.mid', got: {list(local_files.keys())}"
        )

        # Should NOT have nested folder structure
        nested_path = "Carol Of The Bells/song.ini"
        assert nested_path not in local_files, (
            f"Files should be flattened, but found nested: {nested_path}"
        )

        # CRITICAL: extracted_files dict must also have flattened paths
        # This dict is passed to sync_state.add_archive() for tracking
        assert "song.ini" in extracted, (
            f"extracted_files should have flattened paths, got: {list(extracted.keys())}"
        )
        assert nested_path not in extracted, (
            f"extracted_files should NOT have nested paths, got: {list(extracted.keys())}"
        )

    def test_process_archive_no_flatten_different_name(self, temp_dir):
        """Archive with folder name NOT matching archive name should NOT flatten."""
        from src.sync.downloader import FileDownloader, DownloadTask
        from src.sync.state import SyncState
        from src.sync.cache import scan_local_files

        drive_path = temp_dir / "TestDrive" / "Misc"
        drive_path.mkdir(parents=True)

        # Archive stem: "my_chart"
        # Internal folder: "Completely Different Name" (doesn't match!)
        archive_path = drive_path / "_download_my_chart.zip"
        self._create_test_archive(archive_path, {
            "Completely Different Name/song.ini": "[song]",
            "Completely Different Name/notes.mid": b"MThd",
        })

        sync_state = SyncState(temp_dir)
        sync_state.load()

        downloader = FileDownloader(delete_videos=False)
        task = DownloadTask(
            file_id="mychart",
            local_path=archive_path,
            size=archive_path.stat().st_size,
            md5="mychart123",
            is_archive=True,
            rel_path="TestDrive/Misc/my_chart.zip"
        )

        success, error, _ = downloader.process_archive(
            task, sync_state, archive_rel_path="TestDrive/Misc/my_chart.zip"
        )

        assert success, f"Extraction failed: {error}"

        # Files should be in the subfolder (NOT flattened)
        local_files = scan_local_files(drive_path)

        assert "Completely Different Name/song.ini" in local_files, (
            f"Expected nested structure, got: {list(local_files.keys())}"
        )


    def test_process_archive_no_flatten_multiple_folders(self, temp_dir):
        """Archive with multiple top-level folders should NOT flatten."""
        from src.sync.downloader import FileDownloader, DownloadTask
        from src.sync.state import SyncState
        from src.sync.cache import scan_local_files

        drive_path = temp_dir / "TestDrive" / "Misc"
        drive_path.mkdir(parents=True)

        # Archive with TWO top-level folders - should not flatten
        archive_path = drive_path / "_download_multi_chart.zip"
        self._create_test_archive(archive_path, {
            "Chart One/song.ini": "[song]\nname=One",
            "Chart Two/song.ini": "[song]\nname=Two",
        })

        sync_state = SyncState(temp_dir)
        sync_state.load()

        downloader = FileDownloader(delete_videos=False)
        task = DownloadTask(
            file_id="multi",
            local_path=archive_path,
            size=archive_path.stat().st_size,
            md5="multi123",
            is_archive=True,
            rel_path="TestDrive/Misc/multi_chart.zip"
        )

        success, error, _ = downloader.process_archive(
            task, sync_state, archive_rel_path="TestDrive/Misc/multi_chart.zip"
        )

        assert success, f"Multi-folder extraction failed: {error}"

        # Both folders should exist (not flattened)
        local_files = scan_local_files(drive_path)
        assert "Chart One/song.ini" in local_files, f"Missing Chart One: {list(local_files.keys())}"
        assert "Chart Two/song.ini" in local_files, f"Missing Chart Two: {list(local_files.keys())}"

    def test_process_archive_loose_files_no_folder(self, temp_dir):
        """Archive with loose files (no folder) should extract directly."""
        from src.sync.downloader import FileDownloader, DownloadTask
        from src.sync.state import SyncState
        from src.sync.cache import scan_local_files

        drive_path = temp_dir / "TestDrive" / "Misc"
        drive_path.mkdir(parents=True)

        # Archive with files at root, no containing folder
        archive_path = drive_path / "_download_loose_chart.zip"
        self._create_test_archive(archive_path, {
            "song.ini": "[song]\nname=Loose",
            "notes.mid": b"MThd",
        })

        sync_state = SyncState(temp_dir)
        sync_state.load()

        downloader = FileDownloader(delete_videos=False)
        task = DownloadTask(
            file_id="loose",
            local_path=archive_path,
            size=archive_path.stat().st_size,
            md5="loose123",
            is_archive=True,
            rel_path="TestDrive/Misc/loose_chart.zip"
        )

        success, error, _ = downloader.process_archive(
            task, sync_state, archive_rel_path="TestDrive/Misc/loose_chart.zip"
        )

        assert success, f"Loose files extraction failed: {error}"

        # Files should be directly in drive_path (the chart folder)
        local_files = scan_local_files(drive_path)
        assert "song.ini" in local_files, f"Missing song.ini: {list(local_files.keys())}"
        assert "notes.mid" in local_files, f"Missing notes.mid: {list(local_files.keys())}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
