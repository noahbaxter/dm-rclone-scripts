"""
Tests for manifest chart counting logic.

Tests chart type detection and counting functions.
"""

import pytest

from src.manifest.counter import (
    is_sng_file,
    is_zip_file,
    has_folder_chart_markers,
    count_charts_in_files,
    detect_chart_type_from_filenames,
    ChartType,
)


class TestIsSngFile:
    """Tests for is_sng_file() helper."""

    def test_sng_detected(self):
        assert is_sng_file("chart.sng")
        assert is_sng_file("My Song.sng")

    def test_sng_case_insensitive(self):
        assert is_sng_file("chart.SNG")
        assert is_sng_file("chart.Sng")

    def test_non_sng_not_detected(self):
        assert not is_sng_file("chart.zip")
        assert not is_sng_file("chart.7z")
        assert not is_sng_file("song.ini")
        assert not is_sng_file("sng.txt")  # sng in name but not extension


class TestIsZipFile:
    """Tests for is_zip_file() helper."""

    def test_zip_detected(self):
        assert is_zip_file("chart.zip")

    def test_rar_detected(self):
        assert is_zip_file("chart.rar")

    def test_7z_detected(self):
        assert is_zip_file("chart.7z")

    def test_case_insensitive(self):
        assert is_zip_file("chart.ZIP")
        assert is_zip_file("chart.RAR")
        assert is_zip_file("chart.7Z")

    def test_non_archive_not_detected(self):
        assert not is_zip_file("chart.sng")
        assert not is_zip_file("song.ini")
        assert not is_zip_file("notes.mid")
        assert not is_zip_file("zip.txt")  # zip in name but not extension


class TestHasFolderChartMarkers:
    """Tests for has_folder_chart_markers() helper."""

    def test_song_ini_detected(self):
        assert has_folder_chart_markers({"song.ini", "song.ogg"})

    def test_notes_mid_detected(self):
        assert has_folder_chart_markers({"notes.mid", "song.ogg"})

    def test_notes_chart_detected(self):
        assert has_folder_chart_markers({"notes.chart", "song.ogg"})

    def test_case_insensitive(self):
        assert has_folder_chart_markers({"SONG.INI"})
        assert has_folder_chart_markers({"Notes.Mid"})
        assert has_folder_chart_markers({"NOTES.CHART"})

    def test_non_chart_files_not_detected(self):
        assert not has_folder_chart_markers({"readme.txt", "album.png"})
        assert not has_folder_chart_markers({"song.ogg", "guitar.ogg"})
        assert not has_folder_chart_markers(set())


class TestDetectChartTypeFromFilenames:
    """Tests for detect_chart_type_from_filenames()."""

    def test_sng_type_detected(self):
        assert detect_chart_type_from_filenames(["chart.sng"]) == ChartType.SNG

    def test_zip_type_detected(self):
        assert detect_chart_type_from_filenames(["chart.zip"]) == ChartType.ZIP
        assert detect_chart_type_from_filenames(["chart.rar"]) == ChartType.ZIP
        assert detect_chart_type_from_filenames(["chart.7z"]) == ChartType.ZIP

    def test_folder_type_detected(self):
        assert detect_chart_type_from_filenames(["song.ini", "notes.mid"]) == ChartType.FOLDER
        assert detect_chart_type_from_filenames(["notes.chart", "song.ogg"]) == ChartType.FOLDER

    def test_non_chart_returns_none(self):
        assert detect_chart_type_from_filenames(["readme.txt"]) is None
        assert detect_chart_type_from_filenames(["song.ogg", "album.png"]) is None
        assert detect_chart_type_from_filenames([]) is None


class TestCountChartsInFiles:
    """Tests for count_charts_in_files()."""

    def test_zip_files_counted(self):
        """ZIP archives counted as charts."""
        files = [
            {"path": "Setlist/Artist - Song.zip", "size": 1000},
            {"path": "Setlist/Artist - Song 2.7z", "size": 2000},
        ]
        stats = count_charts_in_files(files)
        assert stats.chart_counts.zip == 2
        assert stats.chart_counts.total == 2

    def test_sng_files_counted(self):
        """.sng files counted as charts."""
        files = [
            {"path": "Setlist/song1.sng", "size": 1000},
            {"path": "Setlist/song2.sng", "size": 2000},
        ]
        stats = count_charts_in_files(files)
        assert stats.chart_counts.sng == 2
        assert stats.chart_counts.total == 2

    def test_folder_charts_counted(self):
        """Folders with song.ini/notes.mid counted as charts."""
        files = [
            {"path": "Setlist/Artist - Song/song.ini", "size": 100},
            {"path": "Setlist/Artist - Song/notes.mid", "size": 500},
            {"path": "Setlist/Artist - Song/song.ogg", "size": 5000},
        ]
        stats = count_charts_in_files(files)
        assert stats.chart_counts.folder == 1
        assert stats.chart_counts.total == 1

    def test_multiple_folder_charts(self):
        """Multiple folder charts in same setlist counted separately."""
        files = [
            {"path": "Setlist/Song1/song.ini", "size": 100},
            {"path": "Setlist/Song1/notes.mid", "size": 500},
            {"path": "Setlist/Song2/song.ini", "size": 100},
            {"path": "Setlist/Song2/notes.mid", "size": 500},
        ]
        stats = count_charts_in_files(files)
        assert stats.chart_counts.folder == 2
        assert stats.chart_counts.total == 2

    def test_subfolder_breakdown(self):
        """Charts grouped by top-level subfolder."""
        files = [
            {"path": "Setlist1/chart.zip", "size": 1000},
            {"path": "Setlist2/chart1.zip", "size": 2000},
            {"path": "Setlist2/chart2.zip", "size": 3000},
        ]
        stats = count_charts_in_files(files)
        assert stats.subfolders["Setlist1"].chart_counts.total == 1
        assert stats.subfolders["Setlist2"].chart_counts.total == 2

    def test_root_level_archives(self):
        """Archives at root level counted."""
        files = [
            {"path": "song.zip", "size": 1000},
        ]
        stats = count_charts_in_files(files)
        assert stats.chart_counts.zip == 1
        assert stats.chart_counts.total == 1

    def test_mixed_types(self):
        """Mixed chart types counted correctly."""
        files = [
            {"path": "Setlist/chart1.zip", "size": 1000},
            {"path": "Setlist/chart2.sng", "size": 2000},
            {"path": "Setlist/Folder Chart/song.ini", "size": 100},
            {"path": "Setlist/Folder Chart/notes.mid", "size": 500},
        ]
        stats = count_charts_in_files(files)
        assert stats.chart_counts.zip == 1
        assert stats.chart_counts.sng == 1
        assert stats.chart_counts.folder == 1
        assert stats.chart_counts.total == 3

    def test_file_count_and_size_tracked(self):
        """Total file count and size tracked."""
        files = [
            {"path": "Setlist/chart.zip", "size": 1000},
            {"path": "Setlist/readme.txt", "size": 500},
        ]
        stats = count_charts_in_files(files)
        assert stats.file_count == 2
        assert stats.total_size == 1500

    def test_empty_files_list(self):
        """Empty file list returns zero counts."""
        stats = count_charts_in_files([])
        assert stats.chart_counts.total == 0
        assert stats.file_count == 0
        assert stats.total_size == 0

    def test_nested_folder_chart(self):
        """Folder charts at any depth counted."""
        files = [
            {"path": "Setlist/SubFolder/Deep/Chart/song.ini", "size": 100},
            {"path": "Setlist/SubFolder/Deep/Chart/notes.mid", "size": 500},
        ]
        stats = count_charts_in_files(files)
        assert stats.chart_counts.folder == 1

    def test_subfolder_sizes(self):
        """Subfolder stats track size correctly."""
        files = [
            {"path": "Setlist1/chart.zip", "size": 1000},
            {"path": "Setlist2/chart.zip", "size": 5000},
        ]
        stats = count_charts_in_files(files)
        assert stats.subfolders["Setlist1"].total_size == 1000
        assert stats.subfolders["Setlist2"].total_size == 5000


class TestChartCountsArithmetic:
    """Tests for ChartCounts dataclass operations."""

    def test_total_property(self):
        """total property sums all types."""
        from src.manifest.counter import ChartCounts
        counts = ChartCounts(folder=5, zip=10, sng=3)
        assert counts.total == 18

    def test_add_operator(self):
        """ChartCounts can be added together."""
        from src.manifest.counter import ChartCounts
        a = ChartCounts(folder=1, zip=2, sng=3)
        b = ChartCounts(folder=4, zip=5, sng=6)
        result = a + b
        assert result.folder == 5
        assert result.zip == 7
        assert result.sng == 9

    def test_to_dict(self):
        """to_dict() returns correct structure."""
        from src.manifest.counter import ChartCounts
        counts = ChartCounts(folder=1, zip=2, sng=3)
        d = counts.to_dict()
        assert d["folder"] == 1
        assert d["zip"] == 2
        assert d["sng"] == 3
        assert d["total"] == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
