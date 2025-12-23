"""
Tests for utility functions.
"""

import pytest

from src.core.formatting import (
    sanitize_filename,
    sanitize_path,
    normalize_fs_name,
    dedupe_files_by_newest,
    format_size,
    format_duration,
    to_posix,
    relative_posix,
    parent_posix,
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

    def test_unicode_nfd_normalized_to_nfc(self):
        """
        NFD (decomposed) Unicode is normalized to NFC (composed).

        This fixes the Pokémon bug where manifest has NFD encoding but
        disk has NFC - without normalization, the paths don't match.
        """
        import unicodedata

        # "Pokémon" in NFC (composed é - single codepoint U+00E9)
        nfc_name = "Pokémon"
        # "Pokémon" in NFD (decomposed é - 'e' + combining acute U+0301)
        nfd_name = unicodedata.normalize("NFD", "Pokémon")

        # Verify they're actually different bytes
        assert nfc_name != nfd_name
        assert len(nfc_name) == 7
        assert len(nfd_name) == 8  # Extra char for combining accent

        # But sanitize_filename should normalize both to NFC
        assert sanitize_filename(nfc_name) == sanitize_filename(nfd_name)
        assert sanitize_filename(nfd_name) == "Pokémon"  # NFC output


class TestNormalizeFsName:
    """Tests for normalize_fs_name() - filesystem name normalization."""

    def test_nfd_normalized_to_nfc(self):
        """NFD (decomposed) names are normalized to NFC (composed)."""
        import unicodedata

        # Various accented characters that decompose differently
        test_cases = [
            "Pokémon",      # é (U+00E9)
            "Bôa",          # ô (U+00F4)
            "Gérard",       # é (U+00E9)
            "Déjà Vu",      # é (U+00E9), à (U+00E0)
        ]

        for name in test_cases:
            nfc = unicodedata.normalize("NFC", name)
            nfd = unicodedata.normalize("NFD", name)

            # NFD should be different bytes than NFC
            assert nfc != nfd, f"{name}: NFC and NFD should differ"

            # Both should normalize to NFC
            assert normalize_fs_name(nfc) == nfc
            assert normalize_fs_name(nfd) == nfc

    def test_ascii_unchanged(self):
        """ASCII names pass through unchanged."""
        assert normalize_fs_name("simple_name") == "simple_name"
        assert normalize_fs_name("Chart - Song") == "Chart - Song"

    def test_already_nfc_unchanged(self):
        """NFC names pass through unchanged."""
        assert normalize_fs_name("Pokémon") == "Pokémon"


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

    def test_forward_slash_in_folder_name(self):
        """
        Folder names with forward slashes (escaped as //) should NOT split.

        Google Drive allows "/" in folder names. When building paths, "//" means
        a literal "/" in the folder name (like "Heart // Mind"), not two path separators.
        Current behavior creates nested folders - this test documents the bug.
        """
        # "Heart // Mind" is ONE folder name containing slashes
        # Expected: "Setlist/Heart -- Mind/song.ini" (slashes become dashes)
        # Current bug: splits into nested folders
        result = sanitize_path("Setlist/Heart // Mind/song.ini")
        assert result == "Setlist/Heart -- Mind/song.ini"

    def test_triple_slash_in_folder_name(self):
        """Triple slashes in folder names."""
        result = sanitize_path("Setlist/A /// B/song.ini")
        assert result == "Setlist/A --- B/song.ini"

    def test_consecutive_slashes_become_dashes(self):
        """Multiple consecutive slashes become multiple dashes (stays as one component)."""
        # "folder//file.txt" is one component "folder//file.txt" → "folder--file.txt"
        assert sanitize_path("folder//file.txt") == "folder--file.txt"


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


class TestCrossPlatformPaths:
    """
    Tests for cross-platform path utilities.

    These ensure consistent forward-slash paths regardless of OS.
    Critical for sync_state.json where paths must match across platforms.
    """

    def test_to_posix_normalizes_backslashes(self):
        """to_posix converts backslashes to forward slashes."""
        assert to_posix("folder\\sub\\file.txt") == "folder/sub/file.txt"
        assert to_posix("a\\b/c\\d") == "a/b/c/d"  # Mixed

    def test_relative_posix_with_real_paths(self, tmp_path):
        """relative_posix produces forward slashes from real filesystem paths."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        test_file = nested / "file.txt"
        test_file.touch()

        result = relative_posix(test_file, tmp_path)
        assert result == "a/b/c/file.txt"
        assert "\\" not in result

    def test_parent_posix_extracts_parent(self):
        """parent_posix returns parent with forward slashes."""
        assert parent_posix("a/b/c/file.txt") == "a/b/c"
        assert parent_posix("file.txt") == "."

    # --- Integration: actual function compatibility ---

    def test_scan_functions_produce_compatible_paths(self, tmp_path):
        """
        THE critical integration test: scan_extracted_files and scan_local_files
        must produce identical path keys for the same files.

        This is the actual bug we fixed - if scan_extracted_files used
        str(path.relative_to()) instead of relative_posix(), it would produce
        backslash paths on Windows that wouldn't match scan_local_files output.
        """
        from src.sync.extractor import scan_extracted_files
        from src.sync.cache import scan_local_files

        # Create nested structure like an extracted archive
        chart_folder = tmp_path / "Setlist" / "Chart Name" / "Subfolder"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        (chart_folder.parent / "album.png").write_bytes(b"image")

        # Scan with both functions
        extracted_paths = set(scan_extracted_files(tmp_path, tmp_path).keys())
        local_paths = set(scan_local_files(tmp_path).keys())

        # They MUST produce identical path sets
        assert extracted_paths == local_paths, (
            f"Path mismatch!\n"
            f"scan_extracted_files: {sorted(extracted_paths)}\n"
            f"scan_local_files: {sorted(local_paths)}"
        )

        # Double-check no backslashes snuck in
        for path in extracted_paths:
            assert "\\" not in path, f"Backslash in extracted path: {path}"
        for path in local_paths:
            assert "\\" not in path, f"Backslash in local path: {path}"

    def test_parent_grouping_consistent(self):
        """
        Simulates purge_planner grouping files by parent folder.
        Parent paths must be consistent for proper chart counting.
        """
        files = [
            "Setlist/ChartA/song.ini",
            "Setlist/ChartA/notes.mid",
            "Setlist/ChartB/song.ini",
            "Setlist/ChartB/notes.mid",
        ]

        # Group by parent (simulates chart counting)
        parents = set()
        for f in files:
            parents.add(parent_posix(f))

        assert len(parents) == 2
        assert "Setlist/ChartA" in parents
        assert "Setlist/ChartB" in parents


class TestManifestPathSanitization:
    """Tests for manifest path sanitization at load time."""

    def test_manifest_paths_sanitized_on_fetch(self):
        """
        Manifest file paths are sanitized when fetched.

        This ensures NFD Unicode, illegal chars, etc. are normalized
        at the source so downstream code gets clean paths.
        """
        import unicodedata
        from src.manifest.fetch import _sanitize_manifest_paths

        # Simulate manifest with problematic paths
        manifest = {
            "folders": [{
                "name": "TestDrive",
                "folder_id": "abc123",
                "files": [
                    # NFD Unicode (decomposed é)
                    {"id": "1", "path": unicodedata.normalize("NFD", "Pokémon/song.ini"), "size": 100},
                    # Illegal chars
                    {"id": "2", "path": "Title: Subtitle/chart.zip", "size": 200},
                    # Trailing space (Windows issue)
                    {"id": "3", "path": "Artist /notes.mid", "size": 50},
                ]
            }]
        }

        result = _sanitize_manifest_paths(manifest)

        paths = [f["path"] for f in result["folders"][0]["files"]]

        # NFD should be normalized to NFC
        assert paths[0] == "Pokémon/song.ini"
        assert len(paths[0].split("/")[0]) == 7  # NFC "Pokémon" is 7 chars

        # Colon should become " -"
        assert paths[1] == "Title - Subtitle/chart.zip"

        # Trailing space should be stripped
        assert paths[2] == "Artist/notes.mid"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
