"""
Base progress tracking for async operations.
"""

import threading


class ProgressTracker:
    """Base class for thread-safe progress tracking."""

    def __init__(self):
        self.lock = threading.Lock()
        self._closed = False
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        """Signal cancellation."""
        self._cancelled = True

    def write(self, msg: str):
        """Write a message (thread-safe)."""
        with self.lock:
            print(msg)

    def close(self):
        """Close the progress tracker."""
        with self.lock:
            self._closed = True
