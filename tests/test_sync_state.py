"""
Tests for SyncState integration with sync status and purge detection.

Verifies that:
- Archives tracked in sync_state are recognized as synced
- get_sync_status uses sync_state for archive detection
- Purge planner uses sync_state to avoid flagging synced files
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.state import SyncState
from src.sync.status import get_sync_status
from src.sync.purge_planner import find_extra_files_sync_state


class TestSyncStateArchiveTracking:
    """Tests for SyncState archive tracking."""

    @pytest.fixture
    def temp_sync_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_archive_synced_detection(self, temp_sync_root):
        """SyncState correctly identifies synced archives by MD5."""
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Add an archive
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            archive_size=1000000,
            files={"song.ini": 100, "notes.mid": 500}
        )

        # Check synced with correct MD5
        assert sync_state.is_archive_synced("TestDrive/Setlist/pack.7z", "abc123")

        # Check not synced with wrong MD5
        assert not sync_state.is_archive_synced("TestDrive/Setlist/pack.7z", "wrong_md5")

        # Check not synced for non-existent archive
        assert not sync_state.is_archive_synced("NonExistent/archive.7z", "abc123")

    def test_archive_files_tracked(self, temp_sync_root):
        """SyncState tracks extracted files under archive."""
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="def456",
            archive_size=5000,
            files={
                "song.ini": 100,
                "notes.mid": 500,
                "song.ogg": 4000
            }
        )

        # Get all tracked files
        all_files = sync_state.get_all_files()

        # Files should be at parent path (not under archive name)
        assert "TestDrive/Setlist/song.ini" in all_files
        assert "TestDrive/Setlist/notes.mid" in all_files
        assert "TestDrive/Setlist/song.ogg" in all_files

        # Verify NOT under archive name (the old broken behavior)
        assert "TestDrive/Setlist/Chart.7z/song.ini" not in all_files

    def test_sync_state_persistence(self, temp_sync_root):
        """SyncState saves and loads correctly."""
        # Create and save
        sync_state = SyncState(temp_sync_root)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Chart.7z",
            md5="persist123",
            archive_size=1000,
            files={"song.ini": 50}
        )
        sync_state.save()

        # Load fresh instance
        sync_state2 = SyncState(temp_sync_root)
        sync_state2.load()

        assert sync_state2.is_archive_synced("TestDrive/Chart.7z", "persist123")
        assert "TestDrive/song.ini" in sync_state2.get_all_files()

    def test_remove_archive(self, temp_sync_root):
        """Removing an archive removes it and its tracked files."""
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Add archive
        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="remove_me",
            archive_size=1000,
            files={"song.ini": 50, "notes.mid": 100}
        )

        # Verify it's tracked
        assert sync_state.is_archive_synced("TestDrive/Setlist/Chart.7z", "remove_me")
        assert "TestDrive/Setlist/song.ini" in sync_state.get_all_files()

        # Remove it
        sync_state.remove_archive("TestDrive/Setlist/Chart.7z")

        # Verify it's gone
        assert not sync_state.is_archive_synced("TestDrive/Setlist/Chart.7z", "remove_me")
        assert "TestDrive/Setlist/song.ini" not in sync_state.get_all_files()
        assert "TestDrive/Setlist/notes.mid" not in sync_state.get_all_files()


class TestGetSyncStatusWithSyncState:
    """Tests for get_sync_status using sync_state."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_archive_recognized_as_synced(self, temp_dir):
        """get_sync_status recognizes archives tracked in sync_state."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "notes.mid").write_bytes(b"midi")

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="test_md5_hash",
            archive_size=5000,
            files={"song.ini": 6, "notes.mid": 4}
        )

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [
                {
                    "path": "Setlist/pack.7z",
                    "md5": "test_md5_hash",
                    "size": 5000
                }
            ]
        }

        status = get_sync_status([folder], temp_dir, None, sync_state)

        assert status.synced_charts == 1
        assert status.total_charts == 1

    def test_archive_not_synced_without_sync_state(self, temp_dir):
        """Without sync_state (and no check.txt), archive shows as not synced."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        (folder_path / "song.ini").write_text("[song]")

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [
                {
                    "path": "Setlist/pack.7z",
                    "md5": "test_md5_hash",
                    "size": 5000
                }
            ]
        }

        status = get_sync_status([folder], temp_dir, None, None)

        assert status.synced_charts == 0
        assert status.total_charts == 1


class TestPurgePlannerWithSyncState:
    """Tests for purge planner using sync_state."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_synced_files_not_purgeable(self, temp_dir):
        """Files tracked in sync_state are not flagged as purgeable."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "notes.mid").write_bytes(b"midi")

        # Create sync_state tracking these files
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="xyz789",
            archive_size=1000,
            files={"song.ini": 6, "notes.mid": 4}
        )

        # Use find_extra_files_sync_state
        extras = find_extra_files_sync_state(
            folder_name="TestDrive",
            folder_path=temp_dir / "TestDrive",
            sync_state=sync_state
        )

        # No files should be flagged as extra
        assert len(extras) == 0

    def test_untracked_files_are_purgeable(self, temp_dir):
        """Files NOT in sync_state are flagged as purgeable."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "extra_file.txt").write_text("extra")

        # Create sync_state tracking only song.ini
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="xyz789",
            archive_size=1000,
            files={"song.ini": 6}
        )

        extras = find_extra_files_sync_state(
            folder_name="TestDrive",
            folder_path=temp_dir / "TestDrive",
            sync_state=sync_state
        )

        # Only extra_file.txt should be flagged
        extra_names = [f.name for f, _ in extras]
        assert "extra_file.txt" in extra_names
        assert "song.ini" not in extra_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
