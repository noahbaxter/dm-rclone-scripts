"""
Keyboard input handling for DM Chart Sync.

Provides ESC-aware input functions for better UX.
"""

import sys
import os
import time
from contextlib import contextmanager

# Platform-specific imports
if os.name == 'nt':
    import msvcrt
else:
    import fcntl
    import termios
    import tty
    import select


class CancelInput(Exception):
    """Raised when user cancels input with ESC."""
    pass


@contextmanager
def raw_terminal():
    """Context manager for raw terminal mode (Unix only, no-op on Windows)."""
    if os.name == 'nt':
        yield None
    else:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            yield fd
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@contextmanager
def cbreak_noecho():
    """Context manager for cbreak mode with echo disabled (Unix only, no-op on Windows).

    Unlike raw mode, this preserves output processing (newlines work correctly)
    while disabling input echo and line buffering.
    """
    if os.name == 'nt':
        yield None
    else:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            # Copy settings
            new_settings = termios.tcgetattr(fd)
            # Disable echo and canonical mode (line buffering)
            new_settings[3] = new_settings[3] & ~(termios.ECHO | termios.ICANON)
            # Set minimum chars to read = 1, timeout = 0
            new_settings[6][termios.VMIN] = 1
            new_settings[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, new_settings)
            yield fd
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def read_escape_sequence(fd) -> str:
    """
    Read remaining characters of an escape sequence after ESC was detected.

    Call this after reading \\x1b to get the full sequence.
    Returns the extra characters (not including the initial ESC).
    Unix only - Windows handles escape sequences differently.
    """
    if os.name == 'nt':
        return ''

    # Set non-blocking mode temporarily
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    try:
        # Small delay to let escape sequence arrive (slow terminals)
        time.sleep(0.02)
        # Read any immediately available characters
        extra = ''
        try:
            extra = sys.stdin.read(10)
        except (IOError, BlockingIOError):
            pass
        return extra
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)


# Special key constants
KEY_UP = "KEY_UP"
KEY_DOWN = "KEY_DOWN"
KEY_LEFT = "KEY_LEFT"
KEY_RIGHT = "KEY_RIGHT"
KEY_PAGE_UP = "KEY_PAGE_UP"
KEY_PAGE_DOWN = "KEY_PAGE_DOWN"
KEY_ENTER = "KEY_ENTER"
KEY_ESC = "KEY_ESC"
KEY_BACKSPACE = "KEY_BACKSPACE"
KEY_TAB = "KEY_TAB"
KEY_SPACE = "KEY_SPACE"

# Platform-specific key code mappings (escape sequences -> KEY_* constants)
UNIX_ESCAPE_CODES = {
    '[A': KEY_UP,
    '[B': KEY_DOWN,
    '[C': KEY_RIGHT,
    '[D': KEY_LEFT,
    '[5~': KEY_PAGE_UP,
    '[6~': KEY_PAGE_DOWN,
}

WINDOWS_KEY_CODES = {
    b'H': KEY_UP,
    b'P': KEY_DOWN,
    b'K': KEY_LEFT,
    b'M': KEY_RIGHT,
    b'I': KEY_PAGE_UP,
    b'Q': KEY_PAGE_DOWN,
}

# Special character mappings (char -> (KEY_* constant, raw char for non-special mode))
UNIX_SPECIAL_CHARS = {
    '\r': (KEY_ENTER, '\r'),
    '\n': (KEY_ENTER, '\n'),
    '\x7f': (KEY_BACKSPACE, '\x7f'),
    '\x08': (KEY_BACKSPACE, '\x08'),
    '\t': (KEY_TAB, '\t'),
    ' ': (KEY_SPACE, ' '),
}

WINDOWS_SPECIAL_CHARS = {
    b'\r': (KEY_ENTER, '\r'),
    b'\x08': (KEY_BACKSPACE, '\x08'),
    b'\t': (KEY_TAB, '\t'),
    b' ': (KEY_SPACE, ' '),
}


# Single-letter menu commands that return immediately (no Enter needed)
INSTANT_MENU_COMMANDS = 'QAXCRP'


def getch(return_special_keys: bool = False) -> str:
    """
    Read a single character from stdin without echo.

    Args:
        return_special_keys: If True, return KEY_* constants for arrow keys etc.
                            If False, return '' for arrow keys (backward compat)

    Returns the character, or special strings:
    - KEY_ESC for standalone ESC
    - KEY_UP/DOWN/LEFT/RIGHT for arrow keys (if return_special_keys=True)
    - KEY_ENTER for Enter
    - '' for ignored escape sequences (if return_special_keys=False)
    """
    if os.name == 'nt':
        # Windows
        ch = msvcrt.getch()

        # Arrow/page keys send two bytes: 0xe0 or 0x00 followed by key code
        if ch in (b'\xe0', b'\x00'):
            key_code = msvcrt.getch()
            if return_special_keys:
                key = WINDOWS_KEY_CODES.get(key_code, '')
                if key:
                    return key
            return ''

        # ESC - check if it's part of a sequence or standalone
        if ch == b'\x1b':
            if msvcrt.kbhit():
                msvcrt.getch()  # Consume [
                if msvcrt.kbhit():
                    msvcrt.getch()  # Consume direction char
                return ''
            return KEY_ESC if return_special_keys else '\x1b'

        # Special characters (Enter, Backspace, Tab, Space)
        if ch in WINDOWS_SPECIAL_CHARS:
            key, raw = WINDOWS_SPECIAL_CHARS[ch]
            return key if return_special_keys else raw

        return ch.decode('utf-8', errors='ignore')
    else:
        # Unix/Mac
        with raw_terminal() as fd:
            ch = sys.stdin.read(1)

            # Special characters (Enter, Backspace, Tab, Space)
            if ch in UNIX_SPECIAL_CHARS:
                key, raw = UNIX_SPECIAL_CHARS[ch]
                return key if return_special_keys else raw

            # Escape sequences (arrow keys, etc.)
            if ch == '\x1b':
                extra = read_escape_sequence(fd)
                if extra:
                    if return_special_keys:
                        key = UNIX_ESCAPE_CODES.get(extra, '')
                        if key:
                            return key
                    return ''  # Unknown escape sequence
                else:
                    # Standalone ESC
                    return KEY_ESC if return_special_keys else '\x1b'

            return ch


def check_esc_pressed() -> bool:
    """
    Non-blocking check if ESC was pressed.

    Returns True if ESC is in the input buffer.
    """
    if os.name == 'nt':
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            return ch == b'\x1b'
        return False
    else:
        with raw_terminal():
            if select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                return ch == '\x1b'
            return False


def input_with_esc(prompt: str = "") -> str:
    """
    Read a line of input, but allow ESC to cancel.

    Args:
        prompt: Prompt to display

    Returns:
        The input string

    Raises:
        CancelInput: If ESC is pressed
    """
    if prompt:
        print(prompt, end='', flush=True)

    result = []

    while True:
        ch = getch()

        if not ch:  # Empty (ignored key like arrow)
            continue
        elif ch == '\x1b':  # ESC
            print()  # New line
            raise CancelInput()
        elif ch in ('\r', '\n'):  # Enter
            print()  # New line
            return ''.join(result)
        elif ch == '\x7f' or ch == '\x08':  # Backspace
            if result:
                result.pop()
                # Move cursor back, overwrite with space, move back again
                print('\b \b', end='', flush=True)
        elif ch >= ' ':  # Printable character
            result.append(ch)
            print(ch, end='', flush=True)


def wait_for_key(prompt: str = "Press Enter to continue...", allow_esc: bool = True) -> bool:
    """
    Wait for a key press.

    Args:
        prompt: Prompt to display
        allow_esc: If True, ESC will raise CancelInput

    Returns:
        True if Enter was pressed, False otherwise

    Raises:
        CancelInput: If ESC is pressed and allow_esc is True
    """
    print(prompt, end='', flush=True)

    while True:
        ch = getch()

        if not ch:  # Empty (ignored key like arrow)
            continue
        elif ch == '\x1b' and allow_esc:  # ESC
            print()
            raise CancelInput()
        elif ch in ('\r', '\n'):  # Enter
            print()
            return True
        # Ignore other keys


def menu_input(prompt: str = "") -> str:
    """
    Read menu input (single character or short string).

    For single-char menus, returns immediately on keypress.
    For multi-char input (like "1,2,3"), waits for Enter.

    Args:
        prompt: Prompt to display

    Returns:
        The input string (uppercase)

    Raises:
        CancelInput: If ESC is pressed
    """
    if prompt:
        print(prompt, end='', flush=True)

    result = []

    while True:
        ch = getch()

        if not ch:  # Empty (ignored key like arrow)
            continue
        elif ch == '\x1b':  # ESC
            print()
            raise CancelInput()
        elif ch in ('\r', '\n'):  # Enter
            print()
            return ''.join(result).upper()
        elif ch == '\x7f' or ch == '\x08':  # Backspace
            if result:
                result.pop()
                print('\b \b', end='', flush=True)
        elif ch >= ' ':  # Printable
            result.append(ch)
            print(ch, end='', flush=True)

            # For single letter commands, return immediately
            if len(result) == 1 and ch.upper() in INSTANT_MENU_COMMANDS:
                print()
                return ch.upper()


def flush_input():
    """
    Flush any pending input from stdin.

    Call this before rendering to prevent escape sequence artifacts
    when keys are pressed rapidly.
    """
    if os.name == 'nt':
        while msvcrt.kbhit():
            msvcrt.getch()
    else:
        import fcntl
        fd = sys.stdin.fileno()
        # Save terminal settings
        old_settings = termios.tcgetattr(fd)
        # Save file flags
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        try:
            # Set raw mode and non-blocking
            tty.setraw(fd)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            # Drain all pending input
            while True:
                try:
                    ch = sys.stdin.read(1)
                    if not ch:
                        break
                except (IOError, BlockingIOError):
                    break
        finally:
            # Restore terminal settings and flags
            fcntl.fcntl(fd, fcntl.F_SETFL, flags)
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def wait_with_skip(seconds: float = 2.0, message: str = ""):
    """
    Wait for specified seconds, but any keypress skips immediately.

    Args:
        seconds: How long to wait (default 2 seconds)
        message: Optional message to display (e.g., "Press any key to continue...")
    """
    if message:
        print(f"\n{message}")
    if os.name == 'nt':
        end_time = time.time() + seconds
        while time.time() < end_time:
            if msvcrt.kbhit():
                msvcrt.getch()  # Consume the keypress
                break
            time.sleep(0.05)
    else:
        with raw_terminal():
            end_time = time.time() + seconds
            while time.time() < end_time:
                remaining = end_time - time.time()
                if remaining <= 0:
                    break
                if select.select([sys.stdin], [], [], min(0.05, remaining))[0]:
                    sys.stdin.read(1)  # Consume the keypress
                    break
    # Flush any remaining input (e.g., rest of escape sequences)
    flush_input()
