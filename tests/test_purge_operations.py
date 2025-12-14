"""
Tests for purge operations.

Focus: Verify that count_purgeable_detailed() accurately predicts what
purge_all_folders() will delete. Uses sync_state for tracking files.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.sync import (
    count_purgeable_detailed,
    PurgeStats,
    clear_cache,
)
from src.sync.purge_planner import find_extra_files
from src.sync.state import SyncState

# Backwards compat alias
clear_scan_cache = clear_cache


class TestFindExtraFiles:
    """
    Tests that find_extra_files() correctly identifies untracked files.
    """

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()  # Ensure clean state
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_tracked_file_not_marked_as_extra(self, temp_dir):
        """
        Files tracked in sync_state should not be flagged as extra.
        """
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir()

        # Create file on disk
        (folder_path / "song.zip").write_bytes(b"test content")

        # Track in sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file(f"{folder_name}/song.zip", size=12)

        extras = find_extra_files(folder_name, folder_path, sync_state, set())
        assert len(extras) == 0, f"Tracked file incorrectly marked as extra: {extras}"

    def test_actual_extra_files_still_detected(self, temp_dir):
        """Ensure untracked files are detected as extras."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir()

        # Expected file (tracked)
        expected = folder_path / "Expected"
        expected.mkdir()
        (expected / "song.zip").write_bytes(b"expected")

        # Extra file (not tracked)
        extra = folder_path / "NotTracked"
        extra.mkdir()
        (extra / "rogue.zip").write_bytes(b"should be detected")

        # Track only expected file
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file(f"{folder_name}/Expected/song.zip", size=8)

        extras = find_extra_files(folder_name, folder_path, sync_state, set())
        assert len(extras) == 1
        assert extras[0][0].name == "rogue.zip"


class TestManifestProtectsFiles:
    """
    Integration tests for the bug where files matching manifest but not in
    sync_state were incorrectly flagged for deletion.

    This simulates rclone users who have files that match the manifest
    but haven't been downloaded by Synchotic (no sync_state entries).
    """

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_manifest_files_not_flagged_for_deletion_with_empty_sync_state(self, temp_dir):
        """
        Files that match manifest paths should NOT be flagged for purge,
        even if sync_state exists but is EMPTY.

        This is the core bug: sync_state exists (gets created on startup) but has
        no entries for files downloaded by rclone. The old code only checked
        sync_state, so all files were flagged as "extra" for deletion.

        This test uses an EMPTY sync_state (not None) to reproduce the actual bug.
        """
        folder_path = temp_dir / "TestDrive"
        setlist = folder_path / "Setlist" / "SomeChart"
        setlist.mkdir(parents=True)

        # Create files on disk that match manifest exactly (simulating rclone download)
        (setlist / "song.ini").write_text("[song]\nname=Test")
        (setlist / "notes.mid").write_bytes(b"midi data")
        (setlist / "song.ogg").write_bytes(b"audio data")

        # Manifest has these exact paths
        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [
                {"path": "Setlist/SomeChart/song.ini", "size": 18, "md5": "a"},
                {"path": "Setlist/SomeChart/notes.mid", "size": 9, "md5": "b"},
                {"path": "Setlist/SomeChart/song.ogg", "size": 10, "md5": "c"},
            ]
        }]

        # Create EMPTY sync_state (not None) - this is what happens on first run
        # The bug was: empty sync_state means nothing is tracked, so everything
        # gets flagged as "extra" even though files match manifest
        sync_state = SyncState(temp_dir)
        sync_state.load()  # Empty, no entries

        stats = count_purgeable_detailed(folders, temp_dir, user_settings=None, sync_state=sync_state)

        # Files matching manifest should NOT be flagged as extra
        # OLD BUG: This would be 3 (all files flagged for deletion!)
        assert stats.extra_file_count == 0, \
            f"Manifest-matching files incorrectly flagged as extra: {stats.extra_file_count}"
        assert stats.total_files == 0, \
            f"Expected 0 purgeable files, got {stats.total_files}"

    def test_non_manifest_files_still_flagged_with_empty_sync_state(self, temp_dir):
        """
        Files that DON'T match manifest should still be flagged for deletion,
        even when using manifest-based detection.

        This verifies the fix doesn't accidentally protect ALL files.
        """
        folder_path = temp_dir / "TestDrive"
        setlist = folder_path / "Setlist" / "SomeChart"
        setlist.mkdir(parents=True)

        # Create files on disk - some match manifest, some don't
        (setlist / "song.ini").write_text("[song]\nname=Test")
        (setlist / "rogue_file.txt").write_text("not in manifest")

        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [
                {"path": "Setlist/SomeChart/song.ini", "size": 18, "md5": "a"},
            ]
        }]

        # Empty sync_state - simulates first run
        sync_state = SyncState(temp_dir)
        sync_state.load()

        stats = count_purgeable_detailed(folders, temp_dir, user_settings=None, sync_state=sync_state)

        # Only the rogue file should be flagged
        # This proves the fix correctly identifies ACTUAL extras, not just "everything"
        assert stats.extra_file_count == 1, \
            f"Expected 1 extra file, got {stats.extra_file_count}"

    def test_sanitized_paths_match_correctly(self, temp_dir):
        """
        Paths with special characters should still match after sanitization.

        Manifest paths contain special chars (like :), disk paths are sanitized.
        The fix must sanitize manifest paths before comparison.
        """
        folder_path = temp_dir / "TestDrive"
        # Our sanitization converts : to " -"
        setlist = folder_path / "Setlist" / "Song - Remix"
        setlist.mkdir(parents=True)

        (setlist / "song.ini").write_text("[song]")

        # Manifest has path with colon (will be sanitized to " -")
        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [
                {"path": "Setlist/Song: Remix/song.ini", "size": 7, "md5": "a"},
            ]
        }]

        # Empty sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        stats = count_purgeable_detailed(folders, temp_dir, user_settings=None, sync_state=sync_state)

        # File should match after sanitization
        assert stats.extra_file_count == 0, \
            "Sanitized path should match disk path"

    def test_disabled_setlist_files_still_purged(self, temp_dir):
        """
        Files in DISABLED setlists should still be purged, even if they match manifest.
        The manifest protection only applies to enabled content.
        """
        folder_path = temp_dir / "TestDrive"
        enabled = folder_path / "EnabledSetlist"
        enabled.mkdir(parents=True)
        (enabled / "song.ini").write_text("[song]")

        disabled = folder_path / "DisabledSetlist"
        disabled.mkdir(parents=True)
        (disabled / "song.ini").write_text("[song]")

        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [
                {"path": "EnabledSetlist/song.ini", "size": 7, "md5": "a"},
                {"path": "DisabledSetlist/song.ini", "size": 7, "md5": "b"},
            ]
        }]

        mock_settings = Mock()
        mock_settings.is_drive_enabled.return_value = True
        mock_settings.get_disabled_subfolders.return_value = {"DisabledSetlist"}
        mock_settings.delete_videos = False

        # Empty sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        stats = count_purgeable_detailed(folders, temp_dir, mock_settings, sync_state=sync_state)

        # Disabled setlist file should be flagged, enabled should not
        assert stats.chart_count == 1, "Disabled setlist file should be purged"
        assert stats.extra_file_count == 0, "Enabled setlist file should not be extra"


class TestCountMatchesDeletion:
    """
    Tests that count_purgeable_detailed() accurately predicts deletions.

    Uses sync_state for tracking which files are synced.
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

        # Expected file (tracked)
        expected = folder_path / "Expected"
        expected.mkdir()
        (expected / "song.zip").write_bytes(b"x" * 100)

        # Extra file with known size (not tracked)
        extra = folder_path / "Extra"
        extra.mkdir()
        extra_content = b"x" * 500  # 500 bytes
        (extra / "extra.txt").write_bytes(extra_content)

        folders = [{
            "folder_id": "123",
            "name": "TestDrive",
            "files": [{"path": "Expected/song.zip", "size": 100, "md5": "abc"}]
        }]

        # Track expected file
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/Expected/song.zip", size=100)

        stats = count_purgeable_detailed(folders, temp_dir, user_settings=None, sync_state=sync_state)

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
        mock_settings.delete_videos = False

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
        mock_settings.delete_videos = False

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
        """total_files should sum charts + extras + partials + videos."""
        stats = PurgeStats(
            chart_count=10,
            chart_size=1000,
            extra_file_count=5,
            extra_file_size=500,
            partial_count=2,
            partial_size=200,
            video_count=3,
            video_size=300,
        )
        assert stats.total_files == 20  # 10 + 5 + 2 + 3

    def test_total_size_sums_all_categories(self):
        """total_size should sum all size fields."""
        stats = PurgeStats(
            chart_count=10,
            chart_size=1000,
            extra_file_count=5,
            extra_file_size=500,
            partial_count=2,
            partial_size=200,
            video_count=3,
            video_size=300,
        )
        assert stats.total_size == 2000  # 1000 + 500 + 200 + 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
