"""
Base chart abstraction for DM Chart Sync.

Defines the interface that all chart types must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class ChartType(Enum):
    """Types of chart formats."""
    FOLDER = "folder"  # Loose files in a folder
    ZIP = "zip"        # Compressed archive
    SNG = "sng"        # Single .sng container


class ChartState(Enum):
    """Sync state of a chart."""
    UNKNOWN = "unknown"      # Haven't checked yet
    MISSING = "missing"      # Not downloaded
    CURRENT = "current"      # Up to date
    OUTDATED = "outdated"    # Needs update
    PARTIAL = "partial"      # Partially downloaded (folder charts)


@dataclass
class ChartFile:
    """
    A file within a chart (for folder charts) or the chart itself (for zip/sng).

    Attributes:
        id: Google Drive file ID
        path: Relative path within the chart
        size: File size in bytes
        md5: MD5 checksum (if available)
    """
    id: str
    path: str
    size: int = 0
    md5: str = ""


@dataclass
class Chart(ABC):
    """
    Abstract base class for all chart types.

    A chart represents a single song/chart that can be synced.
    Different chart types (folder, zip, sng) implement different
    sync strategies.

    Attributes:
        name: Display name of the chart
        remote_id: Google Drive folder/file ID
        local_path: Local path where chart is/will be stored
        chart_type: The type of chart (folder, zip, sng)
        files: List of files in the chart (for folder charts)
        checksum: Checksum of the archive (for zip/sng charts)
    """
    name: str
    remote_id: str
    local_path: Path
    chart_type: ChartType
    files: List[ChartFile] = field(default_factory=list)
    checksum: str = ""

    # Cached state
    _state: ChartState = field(default=ChartState.UNKNOWN, repr=False)

    @abstractmethod
    def check_state(self) -> ChartState:
        """
        Check the local state of the chart against remote.

        Returns the current sync state (missing, current, outdated, partial).
        This should be a local-only check using cached checksums/sizes.
        """
        pass

    @abstractmethod
    def get_download_tasks(self) -> List[dict]:
        """
        Get the list of download tasks needed to sync this chart.

        Returns a list of dicts with:
        - id: Google Drive file ID
        - local_path: Where to save the file
        - size: Expected file size
        - md5: Expected checksum (optional)
        - post_download: Optional callback after download (for zip extraction)
        """
        pass

    @abstractmethod
    def needs_full_resync(self) -> bool:
        """
        Check if the chart needs a full re-download.

        For folder charts: False (can update individual files)
        For zip charts: True if checksum changed
        For sng charts: True if checksum changed
        """
        pass

    @abstractmethod
    def prepare_for_sync(self) -> None:
        """
        Prepare local state for syncing.

        For folder charts: No-op
        For zip charts: Delete existing folder if checksum changed
        For sng charts: No-op
        """
        pass

    @abstractmethod
    def post_sync(self) -> None:
        """
        Clean up after sync completes.

        For folder charts: No-op
        For zip charts: Extract archive, save checksum, delete zip
        For sng charts: No-op
        """
        pass

    @property
    def state(self) -> ChartState:
        """Get the cached state, or check if unknown."""
        if self._state == ChartState.UNKNOWN:
            self._state = self.check_state()
        return self._state

    def invalidate_state(self) -> None:
        """Invalidate cached state, forcing re-check."""
        self._state = ChartState.UNKNOWN

    @property
    def total_size(self) -> int:
        """Get total size of all files in the chart."""
        return sum(f.size for f in self.files)

    @property
    def file_count(self) -> int:
        """Get number of files in the chart."""
        return len(self.files)

    def __str__(self) -> str:
        return f"{self.name} ({self.chart_type.value})"
