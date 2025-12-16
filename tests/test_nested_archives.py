"""
Tests for nested archive handling in sync status.

Some drives have archives that contain many charts inside (game rips, packs).
Manifest sees: 1 archive file (1 chart)
Reality: 1 archive extracts to N chart folders

The sync status logic must adjust counts using:
1. Local disk scan (if extracted)
2. Admin overrides (if configured)
3. Manifest data (fallback)
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.sync.status import get_sync_status
from src.sync.state import SyncState
from src.stats import ManifestOverrides, SetlistOverride, FolderOverride
from src.stats.local import LocalStatsScanner


class TestNestedArchiveCounts:
    """Tests for nested archive chart count adjustment."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def _create_chart_folder(self, path: Path):
        """Create a minimal chart folder with markers."""
        path.mkdir(parents=True, exist_ok=True)
        (path / "song.ini").write_text("[song]\nname=Test")
        (path / "notes.mid").write_bytes(b"MThd")

    def test_manifest_counts_one_archive_as_one_chart(self, temp_dir):
        """Without adjustments, manifest counts 1 archive = 1 chart."""
        folder = {
            "folder_id": "test_folder",
            "name": "GameRips",
            "files": [
                {"path": "PackA/pack.7z", "md5": "abc123", "size": 1000000}
            ],
            # No subfolders data = no adjustment possible
            "subfolders": []
        }

        status = get_sync_status([folder], temp_dir, None, None)
        assert status.total_charts == 1  # Manifest: 1 archive = 1 chart

    def test_override_adjusts_chart_count(self, temp_dir):
        """Override tells us 1 archive actually contains many charts."""
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "GameRips/PackA/pack.7z",
            md5="abc123",
            archive_size=1000000,
            files={"dummy.txt": 1}
        )

        (temp_dir / "GameRips" / "PackA").mkdir(parents=True)
        (temp_dir / "GameRips" / "PackA" / "dummy.txt").write_text("x")

        folder = {
            "folder_id": "test_folder",
            "name": "GameRips",
            "files": [
                {"path": "PackA/pack.7z", "md5": "abc123", "size": 1000000}
            ],
            "subfolders": [
                {
                    "name": "PackA",
                    "charts": {"total": 50},
                    "total_size": 1000000
                }
            ]
        }

        mock_overrides = ManifestOverrides()
        mock_overrides.overrides["GameRips"] = FolderOverride(
            setlists={"PackA": SetlistOverride(chart_count=50)}
        )
        mock_overrides._loaded = True

        import src.stats as stats_module
        original_get_overrides = stats_module.get_overrides

        try:
            stats_module.get_overrides = lambda _path=None: mock_overrides

            status = get_sync_status([folder], temp_dir, None, sync_state)

            assert status.total_charts == 50
            assert status.synced_charts == 50
        finally:
            stats_module.get_overrides = original_get_overrides

    def test_local_scan_overrides_manifest_count(self, temp_dir):
        """If charts are extracted locally, scan gives accurate count."""
        folder_path = temp_dir / "GameRips" / "PackA"

        for i in range(5):
            self._create_chart_folder(folder_path / f"Song {i}")

        folder = {
            "folder_id": "test_folder",
            "name": "GameRips",
            "files": [
                {"path": "PackA/pack.7z", "md5": "abc123", "size": 1000000}
            ],
            "subfolders": [
                {
                    "name": "PackA",
                    "charts": {"total": 1},  # Manifest thinks 1
                    "total_size": 1000000
                }
            ]
        }

        sync_state = SyncState(temp_dir)
        sync_state.load()
        extracted_files = {}
        for i in range(5):
            # Sizes must match actual files: "[song]\nname=Test" = 16 bytes, "MThd" = 4 bytes
            extracted_files[f"Song {i}/song.ini"] = 16
            extracted_files[f"Song {i}/notes.mid"] = 4
        sync_state.add_archive(
            "GameRips/PackA/pack.7z",
            md5="abc123",
            archive_size=1000000,
            files=extracted_files
        )

        from src.stats.local import clear_local_stats_cache
        clear_local_stats_cache()

        status = get_sync_status([folder], temp_dir, None, sync_state)

        assert status.total_charts == 5
        assert status.synced_charts == 5

    def test_disabled_setlist_excluded_from_adjustment(self, temp_dir):
        """Disabled setlists shouldn't be counted even with override."""
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "GameRips/PackA/pack.7z",
            md5="abc123",
            archive_size=1000000,
            files={"dummy.txt": 1}
        )

        (temp_dir / "GameRips" / "PackA").mkdir(parents=True)
        (temp_dir / "GameRips" / "PackA" / "dummy.txt").write_text("x")

        folder = {
            "folder_id": "test_folder",
            "name": "GameRips",
            "files": [
                {"path": "PackA/pack.7z", "md5": "abc123", "size": 1000000}
            ],
            "subfolders": [
                {
                    "name": "PackA",
                    "charts": {"total": 50},
                    "total_size": 1000000
                }
            ]
        }

        mock_settings = Mock()
        mock_settings.is_drive_enabled.return_value = True
        mock_settings.get_disabled_subfolders.return_value = {"PackA"}
        mock_settings.is_subfolder_enabled.return_value = False

        status = get_sync_status([folder], temp_dir, mock_settings, sync_state)

        assert status.total_charts == 0
        assert status.synced_charts == 0

    def test_multiple_setlists_with_mixed_archives(self, temp_dir):
        """Multiple setlists: some with nested archives, some without."""
        # Setlist 1: nested archive (1 file -> 10 charts via override)
        (temp_dir / "TestDrive" / "NestedSetlist").mkdir(parents=True)
        (temp_dir / "TestDrive" / "NestedSetlist" / "dummy.txt").write_text("x")

        # Setlist 2: regular archives (3 files = 3 charts)
        (temp_dir / "TestDrive" / "RegularSetlist").mkdir(parents=True)
        for i in range(3):
            (temp_dir / "TestDrive" / "RegularSetlist" / f"song{i}.txt").write_text("x")

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/NestedSetlist/big_archive.7z",
            md5="nested_md5",
            archive_size=5000,
            files={"dummy.txt": 1}
        )
        for i in range(3):
            sync_state.add_archive(
                f"TestDrive/RegularSetlist/song{i}.7z",
                md5=f"md5_{i}",
                archive_size=1000,
                files={f"song{i}.txt": 1}
            )

        folder = {
            "folder_id": "test_drive",
            "name": "TestDrive",
            "files": [
                {"path": "NestedSetlist/big_archive.7z", "md5": "nested_md5", "size": 5000},
                {"path": "RegularSetlist/song0.7z", "md5": "md5_0", "size": 1000},
                {"path": "RegularSetlist/song1.7z", "md5": "md5_1", "size": 1000},
                {"path": "RegularSetlist/song2.7z", "md5": "md5_2", "size": 1000},
            ],
            "subfolders": [
                {"name": "NestedSetlist", "charts": {"total": 10}, "total_size": 5000},
                {"name": "RegularSetlist", "charts": {"total": 3}, "total_size": 3000},
            ]
        }

        # Mock override for nested setlist
        mock_overrides = ManifestOverrides()
        mock_overrides.overrides["TestDrive"] = FolderOverride(
            setlists={"NestedSetlist": SetlistOverride(chart_count=10)}
        )
        mock_overrides._loaded = True

        import src.stats as stats_module
        original_get_overrides = stats_module.get_overrides

        try:
            stats_module.get_overrides = lambda _path=None: mock_overrides

            status = get_sync_status([folder], temp_dir, None, sync_state)

            # Total: 10 (nested) + 3 (regular) = 13
            assert status.total_charts == 13
            assert status.synced_charts == 13
        finally:
            stats_module.get_overrides = original_get_overrides


class TestCacheNestedChartScanning:
    """
    Bug #4 regression tests: cache.py scan_for_charts must handle nested charts.

    src/sync/cache.py has its own scan_for_charts() that was buggy - it only
    recursed into subdirs when NO marker was found. This meant nested charts
    (a chart folder containing other chart folders) were undercounted.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def _create_chart_folder(self, path: Path):
        """Create a minimal chart folder with markers."""
        path.mkdir(parents=True, exist_ok=True)
        (path / "song.ini").write_text("[song]\nname=Test")
        (path / "notes.mid").write_bytes(b"MThd")

    def test_cache_scan_nested_charts(self, temp_dir):
        """
        Bug #4 regression test: cache.py must count nested charts.

        Structure:
        GameRip/
          song.ini       <- makes this a chart (1)
          Track01/
            song.ini     <- nested chart (2)
          Track02/
            song.ini     <- nested chart (3)

        Total should be 3, not 1.
        """
        from src.sync.cache import _scan_actual_charts_uncached

        setlist_path = temp_dir / "GameRip"
        self._create_chart_folder(setlist_path)  # Parent is a chart
        self._create_chart_folder(setlist_path / "Track01")
        self._create_chart_folder(setlist_path / "Track02")

        count, size = _scan_actual_charts_uncached(setlist_path)

        assert count == 3, f"Expected 3 charts (parent + 2 nested), got {count}"

    def test_cache_scan_deeply_nested_charts(self, temp_dir):
        """Cache scan handles deeply nested chart structures."""
        from src.sync.cache import _scan_actual_charts_uncached

        # Album / Disc1 / Track01 - each level is a chart
        base = temp_dir / "Album"
        self._create_chart_folder(base)
        self._create_chart_folder(base / "Disc1")
        self._create_chart_folder(base / "Disc1" / "Track01")
        self._create_chart_folder(base / "Disc1" / "Track02")
        self._create_chart_folder(base / "Disc2")

        count, size = _scan_actual_charts_uncached(base)

        assert count == 5, f"Expected 5 charts, got {count}"


class TestNestedChartFolders:
    """Tests for nested chart folders (chart folder containing other chart folders)."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def _create_chart_folder(self, path: Path, extra_files: dict = None):
        """Create a minimal chart folder with markers and optional extra files."""
        path.mkdir(parents=True, exist_ok=True)
        (path / "song.ini").write_text("[song]\nname=Test")
        (path / "notes.mid").write_bytes(b"MThd")
        if extra_files:
            for name, content in extra_files.items():
                (path / name).write_text(content)

    def test_nested_charts_all_counted(self, temp_dir):
        """
        Chart folder containing other chart folders should count all charts.

        Structure:
        GameRip/
          song.ini       <- makes this a chart (1)
          Track01/
            song.ini     <- nested chart (2)
          Track02/
            song.ini     <- nested chart (3)

        Total should be 3, not 1.
        """
        from src.stats.local import LocalStatsScanner, clear_local_stats_cache

        setlist_path = temp_dir / "GameRip"
        self._create_chart_folder(setlist_path)  # Parent is a chart
        self._create_chart_folder(setlist_path / "Track01")
        self._create_chart_folder(setlist_path / "Track02")

        clear_local_stats_cache()
        scanner = LocalStatsScanner()
        stats = scanner.get_setlist_stats(setlist_path)

        assert stats.chart_count == 3

    def test_non_chart_subdirs_size_included(self, temp_dir):
        """
        Non-chart subdirectories should have their size included in parent chart.

        Structure:
        Chart/
          song.ini
          Resources/
            texture.png  <- should be included in Chart's size
        """
        from src.stats.local import LocalStatsScanner, clear_local_stats_cache

        chart_path = temp_dir / "Chart"
        self._create_chart_folder(chart_path)
        resources = chart_path / "Resources"
        resources.mkdir()
        (resources / "texture.png").write_bytes(b"X" * 1000)

        clear_local_stats_cache()
        scanner = LocalStatsScanner()
        stats = scanner.get_setlist_stats(chart_path)

        assert stats.chart_count == 1
        # Size should include song.ini + notes.mid + texture.png
        assert stats.total_size > 1000  # At least the texture file

    def test_nested_chart_sizes_separate(self, temp_dir):
        """
        Nested charts should have separate sizes (no double counting).

        Structure:
        Parent/
          song.ini (100 bytes)
          Child/
            song.ini (50 bytes)

        Parent size = 100, Child size = 50, total = 150 (not 200 from double counting)
        """
        from src.stats.local import LocalStatsScanner, clear_local_stats_cache

        parent_path = temp_dir / "Parent"
        parent_path.mkdir()
        (parent_path / "song.ini").write_bytes(b"X" * 100)

        child_path = parent_path / "Child"
        child_path.mkdir()
        (child_path / "song.ini").write_bytes(b"Y" * 50)

        clear_local_stats_cache()
        scanner = LocalStatsScanner()
        stats = scanner.get_setlist_stats(parent_path)

        assert stats.chart_count == 2
        assert stats.total_size == 150  # 100 + 50, no double counting


class TestLocalScanPriority:
    """Tests for local scan taking priority over everything."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def _create_chart_folder(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        (path / "song.ini").write_text("[song]\nname=Test")
        (path / "notes.mid").write_bytes(b"MThd")

    def test_local_scan_beats_override(self, temp_dir):
        """Local scan is more accurate than override - use it when available."""
        folder_path = temp_dir / "GameRips" / "PackA"

        # Actually extract 3 charts
        for i in range(3):
            self._create_chart_folder(folder_path / f"Song {i}")

        # Override says 50, manifest says 1
        folder = {
            "folder_id": "test_folder",
            "name": "GameRips",
            "files": [
                {"path": "PackA/pack.7z", "md5": "abc123", "size": 1000000}
            ],
            "subfolders": [
                {
                    "name": "PackA",
                    "charts": {"total": 1},
                    "total_size": 1000000
                }
            ]
        }

        sync_state = SyncState(temp_dir)
        sync_state.load()
        for i in range(3):
            sync_state.add_file(f"GameRips/PackA/Song {i}/song.ini", size=20)
            sync_state.add_file(f"GameRips/PackA/Song {i}/notes.mid", size=4)

        # Override says 50
        mock_overrides = ManifestOverrides()
        mock_overrides.overrides["GameRips"] = FolderOverride(
            setlists={"PackA": SetlistOverride(chart_count=50)}
        )
        mock_overrides._loaded = True

        from src.stats.local import clear_local_stats_cache
        clear_local_stats_cache()

        import src.stats as stats_module
        original_get_overrides = stats_module.get_overrides

        try:
            stats_module.get_overrides = lambda _path=None: mock_overrides

            status = get_sync_status([folder], temp_dir, None, sync_state)

            # Local scan found 3, not override's 50
            assert status.total_charts == 3
        finally:
            stats_module.get_overrides = original_get_overrides


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
