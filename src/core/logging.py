"""
Logging utilities for DM Chart Sync.
"""

import re
import sys
from datetime import datetime
from pathlib import Path


class TeeOutput:
    """Write to both stdout and a log file, filtering out UI noise."""

    # Patterns to skip in log file (menus, ASCII art, etc.)
    _SKIP_PATTERNS = [
        r'[╭│╰├╮╯┤─┬┴╔╗╚╝═║]',  # Box drawing characters (menus)
        r'[█▀▄░▒▓]',             # Block characters (ASCII art banner)
        r'[▸▼▲►◀]',              # Menu cursor/expand indicators
        r'↑.*↓.*Navigate',       # Menu navigation instructions
        r'^\s*$',                 # Blank lines
        r'by Dichotic',          # Version tagline (part of banner)
        r'^\s*↓.*MB\s*\(\d+%\)', # Download progress lines (↓ File: X/Y MB (N%))
    ]

    def __init__(self, log_path: Path):
        self.terminal = sys.stdout
        self.log_file = open(log_path, "a", encoding="utf-8")
        self._skip_regex = re.compile('|'.join(self._SKIP_PATTERNS))
        self._line_buffer = ""
        # Write session header
        self.log_file.write(f"\n{'='*60}\n")
        self.log_file.write(f"Session started: {datetime.now().isoformat()}\n")
        self.log_file.write(f"{'='*60}\n\n")
        self.log_file.flush()

    def write(self, message):
        self.terminal.write(message)

        # Strip ANSI escape codes
        clean = re.sub(r'\x1b\[[0-9;]*[mKHJ]', '', message)

        # Buffer partial lines (for \r carriage return handling)
        self._line_buffer += clean

        # Process complete lines
        while '\n' in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split('\n', 1)
            # Skip UI noise
            if not self._skip_regex.search(line):
                # Skip empty lines and lines that are just carriage return overwrites
                stripped = line.rstrip()
                if stripped and not stripped.startswith('\r'):
                    timestamp = datetime.now().strftime("[%H:%M:%S]")
                    self.log_file.write(f"{timestamp} {stripped}\n")

        # Handle \r (carriage return) - only keep the last version
        if '\r' in self._line_buffer:
            self._line_buffer = self._line_buffer.rsplit('\r', 1)[-1]

        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        # Flush any remaining buffer
        if self._line_buffer.strip() and not self._skip_regex.search(self._line_buffer):
            timestamp = datetime.now().strftime("[%H:%M:%S]")
            self.log_file.write(f"{timestamp} {self._line_buffer.rstrip()}\n")
        self.log_file.close()
