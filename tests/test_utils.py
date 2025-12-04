"""
Tests for utility functions.
"""

import pytest

from src.utils import sanitize_filename, sanitize_path


class TestSanitizeFilename:
    """Tests for sanitize_filename() - cross-platform filename safety."""

    def test_colon_becomes_space_dash(self):
        """Colon → ' -' (common in game titles like 'Guitar Hero: Aerosmith')."""
        assert sanitize_filename("Guitar Hero: Aerosmith") == "Guitar Hero - Aerosmith"

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


class TestSanitizePath:
    """Tests for sanitize_path() - sanitizes each path component."""

    def test_single_component(self):
        """Single path component (no slashes)."""
        assert sanitize_path("Guitar Hero: Aerosmith") == "Guitar Hero - Aerosmith"

    def test_multi_component(self):
        """Multiple path components each sanitized independently."""
        assert sanitize_path("Guitar Hero: Aerosmith/song.zip") == "Guitar Hero - Aerosmith/song.zip"

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
