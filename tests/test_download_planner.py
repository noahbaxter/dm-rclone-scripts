"""
Tests for download planner logic.

Integration tests for plan_downloads() - what gets downloaded, skipped, or flagged.
Helper functions (is_archive_file) are tested implicitly through archive detection tests.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.download_planner import plan_downloads, DownloadTask
from src.sync.state import SyncState


class TestPlanDownloadsSkipping:
    """Tests for files that should be skipped."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_google_docs_skipped(self, temp_dir):
        """Files with no MD5 AND no extension are skipped (Google Docs/Sheets)."""
        files = [{"id": "1", "path": "My Document", "size": 0, "md5": ""}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 0
        assert skipped == 1

    def test_file_with_md5_but_no_extension_included(self, temp_dir):
        """Files with MD5 but no extension are included (like _rb3con files)."""
        files = [{"id": "1", "path": "folder/_rb3con", "size": 100, "md5": "abc123"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 1

    def test_video_files_skipped_when_delete_videos_true(self, temp_dir):
        """Video files skipped when delete_videos=True."""
        files = [{"id": "1", "path": "folder/video.mp4", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 0
        assert skipped == 1

    def test_video_files_included_when_delete_videos_false(self, temp_dir):
        """Video files included when delete_videos=False."""
        files = [{"id": "1", "path": "folder/video.mp4", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=False)
        assert len(tasks) == 1

    def test_various_video_extensions_skipped(self, temp_dir):
        """All video extensions are skipped when delete_videos=True."""
        video_extensions = [".mp4", ".avi", ".webm", ".mov", ".mkv"]
        for ext in video_extensions:
            files = [{"id": "1", "path": f"folder/video{ext}", "size": 1000, "md5": "abc"}]
            tasks, skipped, _ = plan_downloads(files, temp_dir, delete_videos=True)
            assert len(tasks) == 0, f"{ext} should be skipped"
            assert skipped == 1


class TestPlanDownloadsArchives:
    """Tests for archive file handling."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_archive_detected_by_extension(self, temp_dir):
        """ZIP/7z/RAR files flagged as archives needing extraction."""
        for ext in [".zip", ".7z", ".rar", ".ZIP", ".7Z", ".RAR"]:
            files = [{"id": "1", "path": f"folder/chart{ext}", "size": 1000, "md5": "abc"}]
            tasks, _, _ = plan_downloads(files, temp_dir)
            assert len(tasks) == 1
            assert tasks[0].is_archive, f"{ext} should be detected as archive"

    def test_archive_download_path_is_temp_file(self, temp_dir):
        """Archives download to _download_ prefixed temp file."""
        files = [{"id": "1", "path": "Setlist/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
        assert "_download_chart.7z" in str(tasks[0].local_path)

    def test_synced_archive_skipped_via_sync_state(self, temp_dir):
        """Archives tracked in sync_state with matching MD5 are skipped."""
        # Create extracted files on disk at the path sync_state will check
        # sync_state looks for files at sync_root / tracked_path
        # so if archive is "TestDrive/folder/chart.7z", files are at "TestDrive/folder/song.ini"
        (temp_dir / "TestDrive" / "folder").mkdir(parents=True)
        (temp_dir / "TestDrive" / "folder" / "song.ini").write_text("[song]")

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 6}
        )

        # plan_downloads receives folder_path = temp_dir / "TestDrive"
        # and file path = "folder/chart.7z", so local_path = temp_dir/TestDrive/folder/chart.7z
        folder_path = temp_dir / "TestDrive"
        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, folder_path, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 0
        assert skipped == 1

    def test_archive_redownloaded_when_md5_changed(self, temp_dir):
        """Archives with different MD5 than sync_state are re-downloaded."""
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="old_md5",
            archive_size=1000,
            files={"song.ini": 6}
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "new_md5"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 1  # MD5 changed, need to re-download

    def test_archive_redownloaded_when_extracted_files_missing(self, temp_dir):
        """Archives re-downloaded if extracted files no longer exist on disk."""
        # Don't create the extracted files on disk
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 6}  # This file doesn't exist on disk
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 1  # Extracted files missing, need to re-download

    def test_archive_redownloaded_when_extracted_file_size_wrong(self, temp_dir):
        """
        Bug #9 regression test: archive extracted files exist but have wrong size.

        sync_state tracks extracted files with their sizes. If disk size differs
        (file corrupted, modified, or extraction was incomplete), should re-download.
        """
        # Create extracted file with WRONG size
        (temp_dir / "TestDrive" / "folder").mkdir(parents=True)
        (temp_dir / "TestDrive" / "folder" / "song.ini").write_text("short")  # 5 bytes

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 100}  # sync_state says 100 bytes, disk has 5
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Should re-download because extracted file size is wrong
        assert len(tasks) == 1, "Should re-download when extracted file size differs"


class TestPlanDownloadsRegularFiles:
    """Tests for regular (non-archive) file handling."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_new_file_downloaded(self, temp_dir):
        """Files not on disk are downloaded."""
        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir)
        assert len(tasks) == 1
        assert not tasks[0].is_archive

    def test_existing_file_skipped_by_size_match(self, temp_dir):
        """Files matching local size are skipped."""
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("content")  # 7 bytes

        files = [{"id": "1", "path": "folder/song.ini", "size": 7, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 0
        assert skipped == 1

    def test_size_mismatch_triggers_download(self, temp_dir):
        """Files with different size than local are downloaded."""
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("old")  # 3 bytes

        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir)
        assert len(tasks) == 1

    def test_sync_state_used_for_regular_files(self, temp_dir):
        """Regular files check sync_state if provided."""
        # Create file on disk
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("content")  # 7 bytes

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=7)

        files = [{"id": "1", "path": "folder/song.ini", "size": 7, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 0
        assert skipped == 1

    def test_sync_state_disk_size_mismatch_triggers_download(self, temp_dir):
        """
        Bug #9 regression test: sync_state says synced but disk size differs.

        This catches the case where a file was downloaded, then modified locally
        (or extracted with wrong size). sync_state thinks it's synced, but disk
        size doesn't match manifest - should re-download.
        """
        # Create file on disk with DIFFERENT size than manifest expects
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("modified content here")  # 21 bytes

        # sync_state says we downloaded it with manifest's expected size
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=100)  # recorded size

        # Manifest says file should be 100 bytes
        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Should re-download because disk size (21) != manifest size (100)
        assert len(tasks) == 1, "Should re-download when disk size differs from manifest"
        assert skipped == 0


class TestPlanDownloadsPathSanitization:
    """Tests for path sanitization during planning."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_colon_sanitized_in_path(self, temp_dir):
        """Colons in paths are sanitized to ' -'."""
        files = [{"id": "1", "path": "Title: Subtitle/song.ini", "size": 100, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
        assert "Title - Subtitle" in str(tasks[0].local_path)

    def test_illegal_chars_sanitized(self, temp_dir):
        """Various illegal characters are sanitized."""
        files = [{"id": "1", "path": "What?/song*.ini", "size": 100, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
        # ? and * should be removed
        assert "?" not in str(tasks[0].local_path)
        assert "*" not in str(tasks[0].local_path)


class TestPlanDownloadsLongPaths:
    """Tests for Windows long path handling."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_long_path_reported_on_windows(self, temp_dir, monkeypatch):
        """Paths exceeding 260 chars on Windows are skipped and reported."""
        monkeypatch.setattr("os.name", "nt")

        # Create a path that will exceed 260 chars
        long_folder = "A" * 200
        files = [{"id": "1", "path": f"{long_folder}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should be skipped due to long path
        assert len(tasks) == 0
        assert len(long_paths) == 1

    def test_long_path_not_checked_on_unix(self, temp_dir, monkeypatch):
        """Long paths are not checked on non-Windows systems."""
        monkeypatch.setattr("os.name", "posix")

        long_folder = "A" * 200
        files = [{"id": "1", "path": f"{long_folder}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should not be skipped on Unix
        assert len(tasks) == 1
        assert len(long_paths) == 0


class TestDownloadTaskDataclass:
    """Tests for DownloadTask dataclass."""

    def test_default_values(self):
        """DownloadTask has sensible defaults."""
        task = DownloadTask(file_id="123", local_path=Path("/tmp/file.txt"))
        assert task.size == 0
        assert task.md5 == ""
        assert task.is_archive is False
        assert task.rel_path == ""

    def test_all_fields_set(self):
        """All fields can be set explicitly."""
        task = DownloadTask(
            file_id="123",
            local_path=Path("/tmp/file.7z"),
            size=1000,
            md5="abc123",
            is_archive=True,
            rel_path="TestDrive/folder/file.7z"
        )
        assert task.file_id == "123"
        assert task.size == 1000
        assert task.md5 == "abc123"
        assert task.is_archive is True
        assert task.rel_path == "TestDrive/folder/file.7z"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
