"""Tests for delta display modes (size, files, charts).

Verifies that size/files/charts counts are calculated differently
and displayed correctly in each mode.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from src.ui.components.formatting import format_delta, strip_ansi
from src.sync.purge_planner import plan_purge, count_purgeable_files, PurgeStats


class TestFormatDeltaModes:
    """Test format_delta with different modes."""

    def test_size_mode_shows_sizes(self):
        """Size mode should show sizes, not counts."""
        result = format_delta(
            add_size=1024 * 1024,  # 1 MB
            add_files=10,
            add_charts=5,
            remove_size=512 * 1024,  # 512 KB
            remove_files=20,
            remove_charts=8,
            mode="size",
        )
        text = strip_ansi(result)
        assert "+1.0 MB" in text
        assert "-512.0 KB" in text
        assert "files" not in text
        assert "charts" not in text

    def test_files_mode_shows_file_counts(self):
        """Files mode should show file counts."""
        result = format_delta(
            add_size=1024 * 1024,
            add_files=10,
            add_charts=5,
            remove_size=512 * 1024,
            remove_files=20,
            remove_charts=8,
            mode="files",
        )
        text = strip_ansi(result)
        assert "+10 files" in text  # "files " with trailing space
        assert "-20 files" in text
        assert "MB" not in text
        assert "charts" not in text

    def test_charts_mode_shows_chart_counts(self):
        """Charts mode should show chart counts."""
        result = format_delta(
            add_size=1024 * 1024,
            add_files=10,
            add_charts=5,
            remove_size=512 * 1024,
            remove_files=20,
            remove_charts=8,
            mode="charts",
        )
        text = strip_ansi(result)
        assert "+5 charts" in text
        assert "-8 charts" in text
        assert "MB" not in text
        assert "file" not in text

    def test_singular_units(self):
        """Should use singular when count is 1."""
        result = format_delta(add_files=1, add_charts=1, mode="files")
        assert "+1 file]" in strip_ansi(result)

        result = format_delta(add_files=1, add_charts=1, mode="charts")
        assert "+1 chart]" in strip_ansi(result)

    def test_plural_units(self):
        """Should use plural when count > 1."""
        result = format_delta(add_files=2, mode="files")
        assert "+2 files]" in strip_ansi(result)

        result = format_delta(add_charts=2, mode="charts")
        assert "+2 charts]" in strip_ansi(result)

    def test_add_only_white_brackets(self):
        """Add-only delta should have white brackets."""
        result = format_delta(add_size=1024, mode="size")
        # Just verify it doesn't crash and has content
        assert "[" in strip_ansi(result)
        assert "]" in strip_ansi(result)

    def test_remove_only_shows_brackets(self):
        """Remove-only delta should show brackets."""
        result = format_delta(remove_size=1024, mode="size")
        assert "[" in strip_ansi(result)
        assert "-" in strip_ansi(result)

    def test_combined_add_remove(self):
        """Combined add/remove should show both with separator."""
        result = format_delta(
            add_size=1024,
            remove_size=512,
            mode="size",
        )
        text = strip_ansi(result)
        assert "+" in text
        assert "-" in text
        assert "/" in text

    def test_empty_returns_empty_text(self):
        """No add or remove should return empty_text."""
        result = format_delta(empty_text="All synced")
        assert result == "All synced"

    def test_zero_counts_return_empty(self):
        """Zero counts should return empty_text."""
        result = format_delta(
            add_size=0,
            add_files=0,
            add_charts=0,
            remove_size=0,
            remove_files=0,
            remove_charts=0,
            mode="files",
            empty_text="Nothing to do",
        )
        assert result == "Nothing to do"


class TestPurgeChartEstimation:
    """Test chart estimation in purge planner."""

    @pytest.fixture
    def temp_drive(self, tmp_path):
        """Create a temp drive with mixed content types."""
        drive_path = tmp_path / "TestDrive"
        drive_path.mkdir()

        # Setlist with archives (3 archives = 3 charts, but many files inside)
        setlist1 = drive_path / "Archives Setlist"
        setlist1.mkdir()
        (setlist1 / "song1.zip").write_bytes(b"fake zip 1")
        (setlist1 / "song2.rar").write_bytes(b"fake rar 2")
        (setlist1 / "song3.7z").write_bytes(b"fake 7z 3")

        # Setlist with folder charts (2 chart folders, 6 files total)
        setlist2 = drive_path / "Folders Setlist"
        setlist2.mkdir()
        chart1 = setlist2 / "Chart One"
        chart1.mkdir()
        (chart1 / "notes.chart").write_bytes(b"chart data")
        (chart1 / "song.ogg").write_bytes(b"audio data here")
        (chart1 / "album.png").write_bytes(b"image")

        chart2 = setlist2 / "Chart Two"
        chart2.mkdir()
        (chart2 / "notes.mid").write_bytes(b"midi")
        (chart2 / "song.ini").write_bytes(b"ini")
        (chart2 / "guitar.ogg").write_bytes(b"guitar audio")

        # Setlist with mixed content (1 archive + 1 folder = 2 charts, 4 files)
        setlist3 = drive_path / "Mixed Setlist"
        setlist3.mkdir()
        (setlist3 / "archived_song.zip").write_bytes(b"zip content")
        folder_chart = setlist3 / "Folder Song"
        folder_chart.mkdir()
        (folder_chart / "song.ini").write_bytes(b"ini")
        (folder_chart / "notes.chart").write_bytes(b"chart")
        (folder_chart / "audio.ogg").write_bytes(b"audio")

        return tmp_path, drive_path

    def test_disabled_drive_counts_charts_correctly(self, temp_drive):
        """Disabled drive should estimate charts from archives + folder groups."""
        base_path, drive_path = temp_drive

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [],
        }

        # Mock user_settings with drive disabled
        class MockSettings:
            def is_drive_enabled(self, _):
                return False
            def get_disabled_subfolders(self, _):
                return set()
            delete_videos = False

        files, stats = plan_purge([folder], base_path, MockSettings())

        # Total files: 3 + 6 + 4 = 13 files
        assert stats.total_files == 13, f"Expected 13 files, got {stats.total_files}"

        # Estimated charts:
        # - Archives Setlist: 3 archives = 3 charts
        # - Folders Setlist: 2 unique parent folders = 2 charts
        # - Mixed Setlist: 1 archive + 1 folder = 2 charts
        # Total: 7 charts
        assert stats.estimated_charts == 7, f"Expected 7 charts, got {stats.estimated_charts}"

        # Verify files != charts
        assert stats.total_files != stats.estimated_charts

    def test_disabled_setlist_counts_charts(self, temp_drive):
        """Disabled setlist should estimate charts correctly."""
        base_path, drive_path = temp_drive

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [],
        }

        # Mock: drive enabled, but "Archives Setlist" disabled
        class MockSettings:
            def is_drive_enabled(self, _):
                return True
            def get_disabled_subfolders(self, _):
                return {"Archives Setlist"}
            delete_videos = False

        files, stats = plan_purge([folder], base_path, MockSettings())

        # Only Archives Setlist files should be counted
        assert stats.chart_count == 3, f"Expected 3 files from disabled setlist, got {stats.chart_count}"

        # Archives Setlist has 3 archives = 3 charts
        assert stats.estimated_charts == 3, f"Expected 3 charts, got {stats.estimated_charts}"

    def test_count_purgeable_returns_three_values(self, temp_drive):
        """count_purgeable_files should return (files, size, charts)."""
        base_path, drive_path = temp_drive

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [],
        }

        class MockSettings:
            def is_drive_enabled(self, _):
                return False
            def get_disabled_subfolders(self, _):
                return set()
            delete_videos = False

        result = count_purgeable_files([folder], base_path, MockSettings())

        assert len(result) == 3, "Should return 3 values"
        files, size, charts = result

        assert files == 13, f"Expected 13 files, got {files}"
        assert size > 0, "Size should be positive"
        assert charts == 7, f"Expected 7 charts, got {charts}"

        # All three should be different
        assert files != charts, "Files and charts should differ"
        assert files != size, "Files and size should differ"


class TestPartialDownloadsCountAsCharts:
    """Test that partial downloads are counted as charts."""

    @pytest.fixture
    def drive_with_partials(self, tmp_path):
        """Create drive with partial downloads."""
        drive_path = tmp_path / "TestDrive"
        drive_path.mkdir()

        setlist = drive_path / "Setlist"
        setlist.mkdir()

        # 3 partial downloads (incomplete archives)
        (setlist / "_download_song1.zip").write_bytes(b"partial1")
        (setlist / "_download_song2.rar").write_bytes(b"partial2")
        (setlist / "_download_song3.7z").write_bytes(b"partial3")

        # 1 complete file (not a chart)
        (setlist / "readme.txt").write_bytes(b"readme")

        return tmp_path, drive_path

    def test_partials_counted_as_charts(self, drive_with_partials):
        """Each partial download should count as 1 chart."""
        base_path, drive_path = drive_with_partials

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [],
        }

        class MockSettings:
            def is_drive_enabled(self, _):
                return True
            def get_disabled_subfolders(self, _):
                return set()
            delete_videos = False

        files, stats = plan_purge([folder], base_path, MockSettings())

        # 3 partial files
        assert stats.partial_count == 3
        # Each partial = 1 chart
        assert stats.estimated_charts == 3


class TestExtraFilesChartEstimation:
    """Test chart estimation for extra files."""

    @pytest.fixture
    def drive_with_extras(self, tmp_path):
        """Create drive with extra files (not in sync state)."""
        from src.sync.state import SyncState

        drive_path = tmp_path / "TestDrive"
        drive_path.mkdir()

        setlist = drive_path / "Setlist"
        setlist.mkdir()

        # Extra archive (should count as 1 chart)
        (setlist / "extra_song.zip").write_bytes(b"extra archive")

        # Extra non-archive files (should NOT count as charts)
        (setlist / "extra.txt").write_bytes(b"text")
        (setlist / "extra.jpg").write_bytes(b"image")

        # Tracked file (not extra)
        (setlist / "tracked.zip").write_bytes(b"tracked")

        # Set up sync state tracking only tracked.zip
        sync_state = SyncState(tmp_path)
        sync_state.load()
        sync_state.add_file("TestDrive/Setlist/tracked.zip", size=7)
        sync_state.save()

        return tmp_path, drive_path, sync_state

    def test_extra_archives_counted_as_charts(self, drive_with_extras):
        """Only extra archive files should count as estimated charts."""
        base_path, drive_path, sync_state = drive_with_extras

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [],
        }

        class MockSettings:
            def is_drive_enabled(self, _):
                return True
            def get_disabled_subfolders(self, _):
                return set()
            delete_videos = False

        files, stats = plan_purge([folder], base_path, MockSettings(), sync_state)

        # 3 extra files (extra_song.zip, extra.txt, extra.jpg)
        assert stats.extra_file_count == 3

        # Only 1 archive = 1 chart
        assert stats.estimated_charts == 1
