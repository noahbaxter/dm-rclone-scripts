"""
ESC key monitor for cancellable operations.

Runs a background thread that detects ESC keypresses while distinguishing
them from arrow keys and other escape sequences.
"""

import os
import sys
import threading
import time
from typing import Callable

from .keyboard_input import read_escape_sequence

# Platform-specific imports
if os.name == 'nt':
    import msvcrt
else:
    import select
    import termios
    import tty


class EscMonitor:
    """Background thread that monitors for ESC key presses."""

    def __init__(self, on_esc: Callable[[], None]):
        self.on_esc = on_esc
        self._stop = threading.Event()
        self._thread = None
        self._old_settings = None

    def start(self):
        """Start monitoring for ESC."""
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop monitoring."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)

    def _monitor(self):
        """Monitor loop - checks for ESC key."""
        if os.name == 'nt':
            while not self._stop.is_set():
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\x1b':  # ESC or start of escape sequence
                        # Read any following chars
                        seq = b'\x1b'
                        time.sleep(0.01)  # Brief wait for sequence chars
                        while msvcrt.kbhit():
                            seq += msvcrt.getch()
                        # Only trigger if it's just ESC (no sequence)
                        if seq == b'\x1b':
                            self.on_esc()
                            return
                time.sleep(0.05)
        else:
            fd = sys.stdin.fileno()
            try:
                self._old_settings = termios.tcgetattr(fd)
                tty.setcbreak(fd)

                while not self._stop.is_set():
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        ch = sys.stdin.read(1)
                        if ch == '\x1b':  # ESC or start of escape sequence
                            # Read any extra chars (arrow keys, etc.)
                            extra = read_escape_sequence(fd)
                            # Only trigger if it's just ESC alone (no extra chars)
                            if not extra:
                                self.on_esc()
                                return
                            # Otherwise it was an arrow key or other sequence - ignore
            finally:
                if self._old_settings:
                    termios.tcsetattr(fd, termios.TCSADRAIN, self._old_settings)
