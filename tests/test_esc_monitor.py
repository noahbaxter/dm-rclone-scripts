"""
Tests for escape sequence key mappings.

Tests that the key code mappings are correct.
"""

import pytest


class TestEscapeCodeMappings:
    """Test that key code mappings contain expected values."""

    def test_unix_arrow_keys(self):
        """Unix escape codes map to correct KEY_* constants."""
        from src.ui.primitives.keyboard_input import (
            UNIX_ESCAPE_CODES, KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT
        )

        assert UNIX_ESCAPE_CODES['[A'] == KEY_UP
        assert UNIX_ESCAPE_CODES['[B'] == KEY_DOWN
        assert UNIX_ESCAPE_CODES['[C'] == KEY_RIGHT
        assert UNIX_ESCAPE_CODES['[D'] == KEY_LEFT

    def test_unix_page_keys(self):
        """Unix page up/down codes map correctly."""
        from src.ui.primitives.keyboard_input import (
            UNIX_ESCAPE_CODES, KEY_PAGE_UP, KEY_PAGE_DOWN
        )

        assert UNIX_ESCAPE_CODES['[5~'] == KEY_PAGE_UP
        assert UNIX_ESCAPE_CODES['[6~'] == KEY_PAGE_DOWN

    def test_windows_arrow_keys(self):
        """Windows key codes map to correct KEY_* constants."""
        from src.ui.primitives.keyboard_input import (
            WINDOWS_KEY_CODES, KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT
        )

        assert WINDOWS_KEY_CODES[b'H'] == KEY_UP
        assert WINDOWS_KEY_CODES[b'P'] == KEY_DOWN
        assert WINDOWS_KEY_CODES[b'K'] == KEY_LEFT
        assert WINDOWS_KEY_CODES[b'M'] == KEY_RIGHT

    def test_windows_page_keys(self):
        """Windows page up/down codes map correctly."""
        from src.ui.primitives.keyboard_input import (
            WINDOWS_KEY_CODES, KEY_PAGE_UP, KEY_PAGE_DOWN
        )

        assert WINDOWS_KEY_CODES[b'I'] == KEY_PAGE_UP
        assert WINDOWS_KEY_CODES[b'Q'] == KEY_PAGE_DOWN


class TestSpecialCharMappings:
    """Test special character mappings (Enter, Backspace, etc.)."""

    def test_platforms_agree_on_special_keys(self):
        """Both platforms map same logical keys to same KEY_* constants."""
        from src.ui.primitives.keyboard_input import (
            UNIX_SPECIAL_CHARS, WINDOWS_SPECIAL_CHARS,
            KEY_ENTER, KEY_BACKSPACE, KEY_TAB, KEY_SPACE
        )

        # Enter
        assert UNIX_SPECIAL_CHARS['\r'][0] == KEY_ENTER
        assert UNIX_SPECIAL_CHARS['\n'][0] == KEY_ENTER
        assert WINDOWS_SPECIAL_CHARS[b'\r'][0] == KEY_ENTER

        # Backspace (different raw codes, same KEY_*)
        assert UNIX_SPECIAL_CHARS['\x7f'][0] == KEY_BACKSPACE
        assert UNIX_SPECIAL_CHARS['\x08'][0] == KEY_BACKSPACE
        assert WINDOWS_SPECIAL_CHARS[b'\x08'][0] == KEY_BACKSPACE

        # Tab
        assert UNIX_SPECIAL_CHARS['\t'][0] == KEY_TAB
        assert WINDOWS_SPECIAL_CHARS[b'\t'][0] == KEY_TAB

        # Space
        assert UNIX_SPECIAL_CHARS[' '][0] == KEY_SPACE
        assert WINDOWS_SPECIAL_CHARS[b' '][0] == KEY_SPACE
