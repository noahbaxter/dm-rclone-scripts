"""
Tests for purge operations.

Focus: Verify that count_purgeable_detailed() accurately predicts what
purge_all_folders() will delete. The original bug was a 8GB estimate
that deleted 185GB - we must ensure count matches actual deletion.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.sync.operations import (
    find_extra_files,
    count_purgeable_detailed,
    PurgeStats,
    clear_scan_cache,
)


class TestFindExtraFilesSanitization:
    """
    Tests that find_extra_files() correctly handles path sanitization.

    Bug: Manifest paths contain special chars (: ? *) that get sanitized
    on disk. Without sanitization in find_extra_files(), legitimate files
    would be marked as "extras" and purged.
    """

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()  # Ensure clean state
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_colon_in_path_not_marked_as_extra(self, temp_dir):
        """
        THE critical regression test for the sanitization bug.

        Manifest: "Guitar Hero: Aerosmith/song.zip"
        Disk:     "Guitar Hero - Aerosmith/song.zip" (sanitized)

        Before fix: File marked as extra → DATA LOSS
        After fix:  File correctly matched → no deletion
        """
        folder_path = temp_dir / "TestDrive"
        folder_path.mkdir()

        # Create file with sanitized name (as download would create it)
        chart_folder = folder_path / "Guitar Hero - Aerosmith"
        chart_folder.mkdir()
        (chart_folder / "song.zip").write_bytes(b"test content")

        # Manifest has unsanitized path
        folder = {
            "name": "TestDrive",
            "files": [
                {"path": "Guitar Hero: Aerosmith/song.zip", "size": 12, "md5": "abc123"}
            ]
        }

        extras = find_extra_files(folder, temp_dir)
        assert len(extras) == 0, f"Sanitized file incorrectly marked as extra: {extras}"

    def test_actual_extra_files_still_detected(self, temp_dir):
        """Ensure fix didn't break detection of real extra files."""
        folder_path = temp_dir / "TestDrive"
        folder_path.mkdir()

        # Expected file (in manifest)
        expected = folder_path / "Expected"
        expected.mkdir()
        (expected / "song.zip").write_bytes(b"expected")

        # Extra file (not in manifest)
        extra = folder_path / "NotInManifest"
        extra.mkdir()
        (extra / "rogue.zip").write_bytes(b"should be detected")

        folder = {
            "name": "TestDrive",
            "files": [{"path": "Expected/song.zip", "size": 8, "md5": "abc"}]
        }

        extras = find_extra_files(folder, temp_dir)
        assert len(extras) == 1
        assert extras[0][0].name == "rogue.zip"


class TestCountMatchesDeletion:
    """
    Tests that count_purgeable_detailed() accurately predicts deletions.

    The original 185GB bug: count used manifest sizes, deletion used disk sizes.
    These tests verify the count matches what would actually be deleted.
    """

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()  # Ensure clean state
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_extra_file_size_matches_disk_size(self, temp_dir):
        """Count should use actual disk size, not manifest size."""
        folder_path = temp_dir / "TestDrive"
        folder_path.mkdir()

        # Expected file
        expected = folder_path / "Expected"
        expected.mkdir()
        (expected / "song.zip").write_bytes(b"x" * 100)

        # Extra file with known size
        extra = folder_path / "Extra"
        extra.mkdir()
        extra_content = b"x" * 500  # 500 bytes
        (extra / "extra.txt").write_bytes(extra_content)

        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [{"path": "Expected/song.zip", "size": 100, "md5": "abc"}]
        }]

        stats = count_purgeable_detailed(folders, temp_dir, user_settings=None)

        assert stats.extra_file_count == 1
        assert stats.extra_file_size == 500  # Actual disk size

    def test_disabled_drive_counts_all_files(self, temp_dir):
        """When drive is disabled, ALL files should be counted for deletion."""
        folder_path = temp_dir / "TestDrive"
        folder_path.mkdir()

        # Create multiple files
        (folder_path / "file1.txt").write_bytes(b"a" * 100)
        (folder_path / "file2.txt").write_bytes(b"b" * 200)
        sub = folder_path / "subfolder"
        sub.mkdir()
        (sub / "file3.txt").write_bytes(b"c" * 300)

        folders = [{"folder_id": "123", "name": "TestDrive", "files": []}]

        # Mock user_settings with drive disabled
        mock_settings = Mock()
        mock_settings.is_drive_enabled.return_value = False

        stats = count_purgeable_detailed(folders, temp_dir, mock_settings)

        assert stats.chart_count == 3  # All files counted as "charts" (drive content)
        assert stats.chart_size == 600  # 100 + 200 + 300

    def test_disabled_setlist_counts_only_setlist_files(self, temp_dir):
        """Disabled setlist should count only files in that setlist folder."""
        folder_path = temp_dir / "TestDrive"
        folder_path.mkdir()

        # Enabled setlist
        enabled = folder_path / "EnabledSetlist"
        enabled.mkdir()
        (enabled / "song.zip").write_bytes(b"x" * 100)

        # Disabled setlist
        disabled = folder_path / "DisabledSetlist"
        disabled.mkdir()
        (disabled / "song1.zip").write_bytes(b"y" * 200)
        (disabled / "song2.zip").write_bytes(b"z" * 300)

        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [
                {"path": "EnabledSetlist/song.zip", "size": 100, "md5": "a"},
                {"path": "DisabledSetlist/song1.zip", "size": 200, "md5": "b"},
                {"path": "DisabledSetlist/song2.zip", "size": 300, "md5": "c"},
            ]
        }]

        mock_settings = Mock()
        mock_settings.is_drive_enabled.return_value = True
        mock_settings.get_disabled_subfolders.return_value = {"DisabledSetlist"}

        stats = count_purgeable_detailed(folders, temp_dir, mock_settings)

        # Should count the 2 files in disabled setlist (actual disk size)
        assert stats.chart_count == 2
        assert stats.chart_size == 500  # 200 + 300

    def test_empty_folder_doesnt_crash(self, temp_dir):
        """Empty folder should be handled gracefully."""
        folder_path = temp_dir / "EmptyDrive"
        folder_path.mkdir()

        folders = [{"folder_id": "123", "name": "EmptyDrive", "files": []}]

        stats = count_purgeable_detailed(folders, temp_dir, user_settings=None)

        assert stats.chart_count == 0
        assert stats.extra_file_count == 0

    def test_disabled_setlist_with_nested_structure(self, temp_dir):
        """Disabled setlist detection should work with nested folder structures."""
        folder_path = temp_dir / "TestDrive"
        folder_path.mkdir()

        # Create nested structure in disabled setlist
        disabled = folder_path / "DisabledSetlist" / "SubFolder" / "Chart"
        disabled.mkdir(parents=True)
        (disabled / "song.zip").write_bytes(b"x" * 100)

        # Create file directly in disabled setlist root
        (folder_path / "DisabledSetlist" / "root_file.txt").write_bytes(b"y" * 50)

        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [
                {"path": "DisabledSetlist/SubFolder/Chart/song.zip", "size": 100, "md5": "a"},
                {"path": "DisabledSetlist/root_file.txt", "size": 50, "md5": "b"},
            ]
        }]

        mock_settings = Mock()
        mock_settings.is_drive_enabled.return_value = True
        mock_settings.get_disabled_subfolders.return_value = {"DisabledSetlist"}

        stats = count_purgeable_detailed(folders, temp_dir, mock_settings)

        # Both files should be counted (nested + root)
        assert stats.chart_count == 2
        assert stats.chart_size == 150  # 100 + 50


class TestPartialDownloadsPerFolder:
    """Partials should only count for the folder they're in, not globally."""

    def test_partials_not_shared_across_folders(self):
        """DriveB should not inherit DriveA's partial downloads."""
        clear_scan_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)

            # DriveA has partials, DriveB doesn't
            (temp_dir / "DriveA" / "Setlist").mkdir(parents=True)
            (temp_dir / "DriveA" / "Setlist" / "_download_x.7z").write_bytes(b"x" * 100)
            (temp_dir / "DriveB" / "Setlist").mkdir(parents=True)

            folder_a = {"folder_id": "a", "name": "DriveA", "files": []}
            folder_b = {"folder_id": "b", "name": "DriveB", "files": []}

            stats_a = count_purgeable_detailed([folder_a], temp_dir, user_settings=None)
            assert stats_a.partial_count == 1

            clear_scan_cache()

            stats_b = count_purgeable_detailed([folder_b], temp_dir, user_settings=None)
            assert stats_b.partial_count == 0  # Bug: was 1 before fix


class TestPurgeStatsTotal:
    """Tests for PurgeStats total calculations."""

    def test_total_files_sums_all_categories(self):
        """total_files should sum charts + extras + partials."""
        stats = PurgeStats(
            chart_count=10,
            chart_size=1000,
            extra_file_count=5,
            extra_file_size=500,
            partial_count=2,
            partial_size=200,
        )
        assert stats.total_files == 17  # 10 + 5 + 2

    def test_total_size_sums_all_categories(self):
        """total_size should sum all size fields."""
        stats = PurgeStats(
            chart_count=10,
            chart_size=1000,
            extra_file_count=5,
            extra_file_size=500,
            partial_count=2,
            partial_size=200,
        )
        assert stats.total_size == 1700  # 1000 + 500 + 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
