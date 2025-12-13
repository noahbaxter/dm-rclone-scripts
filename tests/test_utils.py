"""
Tests for utility functions.
"""

import pytest

from src.core.formatting import (
    sanitize_filename,
    sanitize_path,
    dedupe_files_by_newest,
    format_size,
    format_duration,
)


class TestSanitizeFilename:
    """Tests for sanitize_filename() - cross-platform filename safety."""

    def test_colon_becomes_space_dash(self):
        """Colon → ' -' (common in titles with subtitles)."""
        assert sanitize_filename("Title: Subtitle") == "Title - Subtitle"

    def test_question_mark_removed(self):
        """Question mark removed entirely."""
        assert sanitize_filename("What?") == "What"
        assert sanitize_filename("Song???") == "Song"

    def test_asterisk_removed(self):
        """Asterisk removed entirely."""
        assert sanitize_filename("Best*Song*Ever") == "BestSongEver"

    def test_angle_brackets_become_dash(self):
        """< and > become dashes."""
        assert sanitize_filename("<intro>") == "-intro-"

    def test_pipe_becomes_dash(self):
        """Pipe becomes dash."""
        assert sanitize_filename("A|B") == "A-B"

    def test_double_quote_becomes_single(self):
        """Double quote → single quote."""
        assert sanitize_filename('Say "Hello"') == "Say 'Hello'"

    def test_backslash_becomes_dash(self):
        """Backslash becomes dash."""
        assert sanitize_filename("AC\\DC") == "AC-DC"

    def test_trailing_dots_stripped(self):
        """Windows silently strips trailing dots - we do it explicitly."""
        assert sanitize_filename("file...") == "file"

    def test_trailing_spaces_stripped(self):
        """Windows silently strips trailing spaces - we do it explicitly."""
        assert sanitize_filename("file   ") == "file"

    def test_windows_reserved_names_prefixed(self):
        """Windows reserved names (CON, PRN, NUL, etc) get underscore prefix."""
        assert sanitize_filename("CON") == "_CON"
        assert sanitize_filename("con") == "_con"  # Case-insensitive
        assert sanitize_filename("NUL.txt") == "_NUL.txt"
        assert sanitize_filename("COM1") == "_COM1"
        assert sanitize_filename("LPT3") == "_LPT3"

    def test_normal_filename_unchanged(self):
        """Clean filenames pass through unchanged."""
        assert sanitize_filename("song.zip") == "song.zip"
        assert sanitize_filename("My Song - Artist") == "My Song - Artist"

    def test_empty_string_unchanged(self):
        """Empty string returns empty."""
        assert sanitize_filename("") == ""

    def test_multiple_illegal_chars(self):
        """Multiple illegal chars in one filename."""
        assert sanitize_filename('What?: "Yes" <No>') == "What - 'Yes' -No-"

    def test_control_characters_become_underscore(self):
        """Control chars (0x00-0x1F, DEL) replaced with underscore."""
        # Tab (0x09), newline (0x0A), carriage return (0x0D)
        assert sanitize_filename("file\tname") == "file_name"
        assert sanitize_filename("file\nname") == "file_name"
        assert sanitize_filename("file\x00name") == "file_name"  # Null byte
        assert sanitize_filename("file\x7fname") == "file_name"  # DEL

    def test_fullwidth_unicode_passes_through(self):
        """Fullwidth Unicode chars are valid filenames, pass unchanged."""
        # Fullwidth colon U+FF1A - NOT the same as ASCII colon
        assert sanitize_filename("Title：Subtitle") == "Title：Subtitle"


class TestSanitizePath:
    """Tests for sanitize_path() - sanitizes each path component."""

    def test_single_component(self):
        """Single path component (no slashes)."""
        assert sanitize_path("Title: Subtitle") == "Title - Subtitle"

    def test_multi_component(self):
        """Multiple path components each sanitized independently."""
        assert sanitize_path("Title: Subtitle/song.zip") == "Title - Subtitle/song.zip"

    def test_deeply_nested(self):
        """Deeply nested paths."""
        result = sanitize_path("Drive/Artist: Name/Album?/song*.zip")
        assert result == "Drive/Artist - Name/Album/song.zip"

    def test_backslash_normalized(self):
        """Backslashes converted to forward slashes first."""
        assert sanitize_path("folder\\file.txt") == "folder/file.txt"

    def test_preserves_structure(self):
        """Path structure preserved, only filenames sanitized."""
        clean_path = "folder/subfolder/file.txt"
        assert sanitize_path(clean_path) == clean_path


class TestDedupeFilesByNewest:
    """Tests for dedupe_files_by_newest() - keeping newest version of duplicate paths."""

    def test_keeps_newest_by_modified_date(self):
        """Basic dedup keeps file with latest modified date."""
        files = [
            {"path": "song.zip", "modified": "2022-01-01T00:00:00Z", "md5": "old"},
            {"path": "song.zip", "modified": "2023-01-01T00:00:00Z", "md5": "new"},
        ]
        result = dedupe_files_by_newest(files)
        assert len(result) == 1
        assert result[0]["md5"] == "new"

    def test_trailing_space_treated_as_duplicate(self):
        """
        THE critical test for the re-download bug.

        Manifest has two entries that differ only by trailing space in folder name:
        - 'Artist /song.rar' (with trailing space, newer)
        - 'Artist/song.rar' (without trailing space, older)

        After sanitization these are the same path, so dedup should catch them.
        """
        files = [
            {"path": "Artist /song.rar", "modified": "2023-01-01T00:00:00Z", "md5": "newer"},
            {"path": "Artist/song.rar", "modified": "2022-01-01T00:00:00Z", "md5": "older"},
        ]
        result = dedupe_files_by_newest(files)
        assert len(result) == 1
        assert result[0]["md5"] == "newer"  # Keeps the newer one

    def test_colon_treated_as_duplicate(self):
        """Paths differing only by colon (sanitized to ' -') are duplicates."""
        files = [
            {"path": "Title: Subtitle/song.zip", "modified": "2023-01-01T00:00:00Z"},
            {"path": "Title - Subtitle/song.zip", "modified": "2022-01-01T00:00:00Z"},
        ]
        result = dedupe_files_by_newest(files)
        assert len(result) == 1

    def test_different_paths_kept(self):
        """Actually different paths are kept separately."""
        files = [
            {"path": "Artist1/song.zip", "modified": "2023-01-01T00:00:00Z"},
            {"path": "Artist2/song.zip", "modified": "2022-01-01T00:00:00Z"},
        ]
        result = dedupe_files_by_newest(files)
        assert len(result) == 2

    def test_empty_list_returns_empty(self):
        """Empty input returns empty output."""
        assert dedupe_files_by_newest([]) == []


class TestFormatSize:
    """Tests for format_size() - human readable byte sizes."""

    def test_bytes(self):
        """Small values shown in bytes."""
        assert format_size(0) == "0.0 B"
        assert format_size(500) == "500.0 B"
        assert format_size(1023) == "1023.0 B"

    def test_kilobytes(self):
        """KB range."""
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"
        assert format_size(1024 * 500) == "500.0 KB"

    def test_megabytes(self):
        """MB range."""
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(1024 * 1024 * 50) == "50.0 MB"

    def test_gigabytes(self):
        """GB range."""
        assert format_size(1024 * 1024 * 1024) == "1.0 GB"
        assert format_size(1024 * 1024 * 1024 * 2.5) == "2.5 GB"

    def test_terabytes(self):
        """TB range."""
        assert format_size(1024 * 1024 * 1024 * 1024) == "1.0 TB"


class TestFormatDuration:
    """Tests for format_duration() - human readable time durations."""

    def test_seconds_only(self):
        """Durations under 60s shown in seconds."""
        assert format_duration(0) == "0.0s"
        assert format_duration(45) == "45.0s"
        assert format_duration(59.9) == "59.9s"

    def test_minutes_and_seconds(self):
        """Durations under 1 hour shown in minutes and seconds."""
        assert format_duration(60) == "1m 0s"
        assert format_duration(90) == "1m 30s"
        assert format_duration(125) == "2m 5s"
        assert format_duration(3599) == "59m 59s"

    def test_hours_and_minutes(self):
        """Durations 1 hour+ shown in hours and minutes."""
        assert format_duration(3600) == "1h 0m"
        assert format_duration(3660) == "1h 1m"
        assert format_duration(7200) == "2h 0m"
        assert format_duration(5400) == "1h 30m"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
