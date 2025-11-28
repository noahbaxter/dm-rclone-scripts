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


# Special key constants
KEY_UP = "KEY_UP"
KEY_DOWN = "KEY_DOWN"
KEY_LEFT = "KEY_LEFT"
KEY_RIGHT = "KEY_RIGHT"
KEY_ENTER = "KEY_ENTER"
KEY_ESC = "KEY_ESC"
KEY_BACKSPACE = "KEY_BACKSPACE"
KEY_TAB = "KEY_TAB"
KEY_SPACE = "KEY_SPACE"


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
        # Windows arrow keys send two bytes: 0xe0 followed by key code
        if ch == b'\xe0' or ch == b'\x00':
            key_code = msvcrt.getch()
            if return_special_keys:
                if key_code == b'H':
                    return KEY_UP
                elif key_code == b'P':
                    return KEY_DOWN
                elif key_code == b'K':
                    return KEY_LEFT
                elif key_code == b'M':
                    return KEY_RIGHT
            return ''
        if ch == b'\x1b':
            # Check for escape sequence
            if msvcrt.kbhit():
                msvcrt.getch()  # Consume [
                if msvcrt.kbhit():
                    msvcrt.getch()  # Consume A/B/C/D
                return ''
            return KEY_ESC if return_special_keys else '\x1b'
        if ch == b'\r':
            return KEY_ENTER if return_special_keys else '\r'
        if ch == b'\x08':
            return KEY_BACKSPACE if return_special_keys else '\x08'
        if ch == b'\t':
            return KEY_TAB if return_special_keys else '\t'
        if ch == b' ':
            return KEY_SPACE if return_special_keys else ' '
        return ch.decode('utf-8', errors='ignore')
    else:
        # Unix/Mac
        with raw_terminal() as fd:
            ch = sys.stdin.read(1)

            # Handle Enter
            if ch in ('\r', '\n'):
                return KEY_ENTER if return_special_keys else ch

            # Handle backspace
            if ch == '\x7f' or ch == '\x08':
                return KEY_BACKSPACE if return_special_keys else ch

            # Handle tab
            if ch == '\t':
                return KEY_TAB if return_special_keys else ch

            # Handle space
            if ch == ' ':
                return KEY_SPACE if return_special_keys else ch

            # Check if this is an escape sequence (arrow keys, etc.)
            if ch == '\x1b':
                import fcntl
                import os as os_module

                # Set non-blocking temporarily
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, flags | os_module.O_NONBLOCK)

                try:
                    # Small delay to let escape sequence arrive
                    time.sleep(0.02)

                    # Try to read more characters
                    extra = ''
                    try:
                        extra = sys.stdin.read(10)  # Read up to 10 chars
                    except (IOError, BlockingIOError):
                        pass

                    if extra:
                        # This was an escape sequence
                        if return_special_keys and extra.startswith('['):
                            # Parse arrow keys: ESC [ A/B/C/D
                            if 'A' in extra:
                                return KEY_UP
                            elif 'B' in extra:
                                return KEY_DOWN
                            elif 'C' in extra:
                                return KEY_RIGHT
                            elif 'D' in extra:
                                return KEY_LEFT
                        return ''  # Unknown escape sequence
                    else:
                        # Standalone ESC
                        return KEY_ESC if return_special_keys else '\x1b'
                finally:
                    # Restore blocking mode
                    fcntl.fcntl(fd, fcntl.F_SETFL, flags)

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
            if len(result) == 1 and ch.upper() in 'QAXCRP':
                print()
                return ch.upper()


def wait_with_skip(seconds: float = 2.0):
    """
    Wait for specified seconds, but any keypress skips immediately.

    Args:
        seconds: How long to wait (default 2 seconds)
    """
    if os.name == 'nt':
        end_time = time.time() + seconds
        while time.time() < end_time:
            if msvcrt.kbhit():
                msvcrt.getch()  # Consume the keypress
                return
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
                    return
