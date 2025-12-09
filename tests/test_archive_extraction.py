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

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
