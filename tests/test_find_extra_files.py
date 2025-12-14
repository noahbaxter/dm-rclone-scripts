"""
Tests for find_extra_files.

Verifies that files tracked in sync_state or manifest aren't flagged as purgeable.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync import clear_cache
from src.sync.purge_planner import find_extra_files
from src.sync.state import SyncState
from src.sync.cache import scan_local_files

# Backwards compat
_scan_local_files = scan_local_files
clear_scan_cache = clear_cache


class TestSyncStateExtraFiles:
    """Tests for sync_state-based extra file detection."""

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()  # Ensure clean state
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_tracked_files_not_flagged_as_extra(self, temp_dir):
        """
        Files tracked in sync_state should not be flagged as extra.
        """
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        # Create files on disk
        (chart_folder / "song.ini").write_text("[song]\nname=Test")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        (chart_folder / "song.ogg").write_bytes(b"audio data")

        # Set up sync_state with these files tracked
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            f"{folder_name}/Setlist/SomeChart/SomeChart.7z",
            md5="abc123def456",
            archive_size=5000,
            files={
                "song.ini": 18,
                "notes.mid": 9,
                "song.ogg": 10
            }
        )

        # Find extra files (no manifest paths)
        extras = find_extra_files(folder_name, folder_path, sync_state, set())

        # Assert: tracked files should NOT be flagged as extra
        extra_names = [f.name for f, _ in extras]
        assert "song.ini" not in extra_names, "song.ini was incorrectly flagged as extra"
        assert "notes.mid" not in extra_names, "notes.mid was incorrectly flagged as extra"
        assert "song.ogg" not in extra_names, "song.ogg was incorrectly flagged as extra"

    def test_untracked_files_flagged_as_extra(self, temp_dir):
        """Files not in sync_state or manifest should be flagged as extra."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        # Create files on disk
        (chart_folder / "song.ini").write_text("[song]\nname=Test")
        (chart_folder / "extra_file.txt").write_text("not tracked")

        # Set up sync_state with only song.ini tracked
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file(f"{folder_name}/Setlist/SomeChart/song.ini", size=18)

        extras = find_extra_files(folder_name, folder_path, sync_state, set())

        extra_names = [f.name for f, _ in extras]
        assert "extra_file.txt" in extra_names, "Untracked file should be flagged"
        assert "song.ini" not in extra_names, "Tracked file should not be flagged"

    def test_empty_sync_state_flags_all_files_without_manifest(self, temp_dir):
        """With empty sync_state and no manifest, all files should be flagged as extra."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "file1.txt").write_text("content1")
        (folder_path / "file2.txt").write_text("content2")

        # Empty sync_state, no manifest paths
        sync_state = SyncState(temp_dir)
        sync_state.load()

        extras = find_extra_files(folder_name, folder_path, sync_state, set())

        assert len(extras) == 2, "All files should be extras with empty sync_state and no manifest"

    def test_manifest_paths_protect_files(self, temp_dir):
        """Files in manifest should not be flagged as extra even without sync_state."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "in_manifest.txt").write_text("content1")
        (folder_path / "not_in_manifest.txt").write_text("content2")

        # Empty sync_state but one file is in manifest
        sync_state = SyncState(temp_dir)
        sync_state.load()

        manifest_paths = {f"{folder_name}/in_manifest.txt"}
        extras = find_extra_files(folder_name, folder_path, sync_state, manifest_paths)

        extra_names = [f.name for f, _ in extras]
        assert "in_manifest.txt" not in extra_names, "Manifest file should be protected"
        assert "not_in_manifest.txt" in extra_names, "Non-manifest file should be flagged"

    def test_no_sync_state_with_manifest(self, temp_dir):
        """With no sync_state (None), manifest paths should still protect files."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "protected.txt").write_text("protected")
        (folder_path / "extra.txt").write_text("extra")

        manifest_paths = {f"{folder_name}/protected.txt"}
        extras = find_extra_files(folder_name, folder_path, None, manifest_paths)

        extra_names = [f.name for f, _ in extras]
        assert len(extras) == 1
        assert "extra.txt" in extra_names


class TestFindExtraFilesWithCache:
    """Tests for find_extra_files when passed pre-scanned local_files."""

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_with_explicit_local_files_param(self, temp_dir):
        """find_extra_files should work correctly when passed cached local_files."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir()

        # Create expected and extra files
        (folder_path / "expected.txt").write_text("expected")
        (folder_path / "extra.txt").write_text("extra")

        # Track expected.txt in sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file(f"{folder_name}/expected.txt", size=8)

        # Pre-scan and pass explicitly (the optimized path)
        local_files = _scan_local_files(folder_path)
        extras = find_extra_files(folder_name, folder_path, sync_state, set(), local_files)

        assert len(extras) == 1
        assert extras[0][0].name == "extra.txt"

    def test_empty_folder_returns_empty(self, temp_dir):
        """Empty folder should return no extras, not crash."""
        folder_name = "EmptyDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir()

        sync_state = SyncState(temp_dir)
        sync_state.load()

        extras = find_extra_files(folder_name, folder_path, sync_state, set())
        assert extras == []

    def test_nonexistent_folder_returns_empty(self, temp_dir):
        """Non-existent folder should return no extras, not crash."""
        folder_name = "DoesNotExist"
        folder_path = temp_dir / folder_name

        sync_state = SyncState(temp_dir)
        sync_state.load()

        extras = find_extra_files(folder_name, folder_path, sync_state, set())
        assert extras == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
