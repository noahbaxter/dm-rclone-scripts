"""
Active downloads display - the fixed bottom section during downloads.

Renders a list of in-progress large file downloads with ANSI cursor
manipulation to update in place without scrolling.
"""

import shutil
import sys
import time
from dataclasses import dataclass, field

from ...core.formatting import format_duration, format_speed
from ..primitives.colors import Colors
from ..primitives.terminal import SECTION_WIDTH, make_separator


@dataclass
class ActiveDownload:
    """Tracks an in-progress large file download."""
    file_id: str
    display_name: str
    path_context: str
    total_bytes: int
    downloaded_bytes: int = 0
    start_time: float = field(default_factory=time.time)


class ActiveDownloadsDisplay:
    """Manages the fixed bottom section showing active downloads."""

    MAX_VISIBLE = 5

    def __init__(self, is_tty: bool = True):
        self._is_tty = is_tty
        self._downloads: dict[str, ActiveDownload] = {}
        self._lines_rendered = 0
        # Aggregate progress tracking
        self._total_files = 0
        self._completed_files = 0
        self._total_bytes = 0
        self._downloaded_bytes = 0
        self._start_time: float = 0
        self._drive_name: str = ""

    def set_aggregate_totals(self, total_files: int, total_bytes: int, drive_name: str = ""):
        """Set the total files and bytes for aggregate progress."""
        self._total_files = total_files
        self._total_bytes = total_bytes
        self._drive_name = drive_name
        self._start_time = time.time()
        self._completed_files = 0
        self._downloaded_bytes = 0

    def update_aggregate_progress(self, completed_files: int, downloaded_bytes: int):
        """Update the aggregate progress counters."""
        self._completed_files = completed_files
        self._downloaded_bytes = downloaded_bytes

    def register(self, file_id: str, display_name: str, path_context: str, total_bytes: int):
        """Register a new active download."""
        self._downloads[file_id] = ActiveDownload(
            file_id=file_id,
            display_name=display_name,
            path_context=path_context,
            total_bytes=total_bytes,
        )

    def update(self, file_id: str, downloaded_bytes: int):
        """Update progress for an active download."""
        if file_id in self._downloads:
            self._downloads[file_id].downloaded_bytes = downloaded_bytes

    def unregister(self, file_id: str):
        """Remove a completed download."""
        self._downloads.pop(file_id, None)

    def clear_display(self):
        """Clear the rendered bottom section from terminal."""
        if not self._is_tty or self._lines_rendered == 0:
            return
        try:
            for _ in range(self._lines_rendered):
                sys.stdout.write("\033[A\033[K")  # Move up + clear line
            sys.stdout.flush()
        except OSError:
            pass  # Terminal closed
        self._lines_rendered = 0

    def render(self) -> list[str]:
        """Render the active downloads section as lines."""
        if not self._downloads and self._total_files == 0:
            return []

        c = Colors
        lines = []
        term_width = shutil.get_terminal_size().columns
        separator = make_separator("─", min(term_width - 2, SECTION_WIDTH))

        # Aggregate progress line ABOVE separator (bold, distinct from per-file)
        if self._total_files > 0:
            pct = self._completed_files / self._total_files * 100
            elapsed = time.time() - self._start_time if self._start_time > 0 else 0

            # Include in-progress bytes from active downloads for live speed
            in_progress_bytes = sum(dl.downloaded_bytes for dl in self._downloads.values())
            total_downloaded = self._downloaded_bytes + in_progress_bytes

            parts = []
            if self._drive_name:
                parts.append(f"[{self._drive_name}]")
            parts.append(f"{pct:.0f}%")
            parts.append(f"{self._completed_files}/{self._total_files}")

            # Speed and ETA (only if we have meaningful data)
            if elapsed > 2 and total_downloaded > 0:
                speed = total_downloaded / elapsed
                parts.append(format_speed(speed))

                remaining_bytes = self._total_bytes - total_downloaded
                if speed > 0 and remaining_bytes > 0:
                    eta = remaining_bytes / speed
                    parts.append(f"~{format_duration(eta)}")

            lines.append(f"  {c.BOLD}{' • '.join(parts)}{c.RESET}")

        # Separator line
        lines.append(separator)

        # Per-file downloads (no header, just the files)
        if not self._downloads:
            return lines

        # Sort by start time (oldest first)
        sorted_downloads = sorted(self._downloads.values(), key=lambda d: d.start_time)

        for dl in sorted_downloads[:self.MAX_VISIBLE]:
            pct = (dl.downloaded_bytes / dl.total_bytes * 100) if dl.total_bytes > 0 else 0
            dl_mb = dl.downloaded_bytes / (1024 * 1024)
            total_mb = dl.total_bytes / (1024 * 1024)

            ctx = f"[{dl.path_context}]" if dl.path_context else ""
            arrow = f"{c.CYAN}↓{c.RESET}"

            # Truncate name if needed (guard against narrow terminals)
            max_name_len = max(10, term_width - 50)
            name = dl.display_name
            if len(name) > max_name_len:
                name = name[:max_name_len - 3] + "..."

            line = f"  {arrow} {c.DIM}{ctx}{c.RESET} {name}  {dl_mb:.0f}/{total_mb:.0f} MB ({pct:.0f}%)"
            lines.append(line)

        # Show overflow indicator
        overflow = len(self._downloads) - self.MAX_VISIBLE
        if overflow > 0:
            lines.append(f"  ... and {overflow} more")

        return lines

    def refresh(self):
        """Clear and redraw the bottom section."""
        if not self._is_tty:
            return

        self.clear_display()

        lines = self.render()
        if lines:
            try:
                for line in lines:
                    print(line)
                self._lines_rendered = len(lines)
            except OSError:
                pass  # Terminal closed
