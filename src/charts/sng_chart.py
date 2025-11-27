"""
SngChart implementation for .sng container files.

A .sng file is a single container that holds all chart data.
No extraction needed - just download the file directly.

Sync strategy:
- Compare file size and/or checksum
- If different, re-download the entire file
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .base import Chart, ChartType, ChartFile, ChartState


@dataclass
class SngChart(Chart):
    """
    A chart stored as a single .sng container file.

    Sync strategy:
    - Compare local file size/checksum with remote
    - If different, re-download entire file
    """

    chart_type: ChartType = field(default=ChartType.SNG, init=False)

    # The single .sng file info
    sng_file: ChartFile = field(default=None)

    def _get_sng_path(self) -> Path:
        """Get the path where the .sng file is/should be stored."""
        if self.sng_file:
            return self.local_path / self.sng_file.path
        return self.local_path / f"{self.name}.sng"

    def check_state(self) -> ChartState:
        """
        Check local state by comparing file size/checksum.

        Returns:
            MISSING: File doesn't exist
            CURRENT: File exists with correct size (and checksum if available)
            OUTDATED: File exists but size/checksum differs
        """
        sng_path = self._get_sng_path()

        if not sng_path.exists():
            return ChartState.MISSING

        if not self.sng_file:
            return ChartState.MISSING

        local_size = sng_path.stat().st_size

        # Check size first (fast)
        if self.sng_file.size and local_size != self.sng_file.size:
            return ChartState.OUTDATED

        # If we have checksums, could verify here
        # For now, size match is sufficient

        return ChartState.CURRENT

    def get_download_tasks(self) -> List[dict]:
        """
        Get download task for the .sng file.

        Returns single task for the .sng file.
        """
        if not self.sng_file:
            return []

        sng_path = self._get_sng_path()

        return [{
            "id": self.sng_file.id,
            "local_path": sng_path,
            "size": self.sng_file.size,
            "md5": self.sng_file.md5,
        }]

    def needs_full_resync(self) -> bool:
        """Sng charts always need full resync if outdated (single file)."""
        state = self.check_state()
        return state in (ChartState.MISSING, ChartState.OUTDATED)

    def prepare_for_sync(self) -> None:
        """Create parent directory if needed."""
        self.local_path.mkdir(parents=True, exist_ok=True)

        # If outdated, delete the existing file
        state = self.check_state()
        if state == ChartState.OUTDATED:
            sng_path = self._get_sng_path()
            if sng_path.exists():
                sng_path.unlink()

    def post_sync(self) -> None:
        """No post-processing needed for .sng files."""
        pass

    @classmethod
    def from_manifest_data(cls, name: str, file_id: str, local_base: Path,
                           size: int = 0, md5: str = "",
                           filename: str = "") -> "SngChart":
        """
        Create a SngChart from manifest data.

        Args:
            name: Chart name (usually filename without extension)
            file_id: Google Drive file ID
            local_base: Base path for local storage
            size: File size
            md5: File checksum
            filename: Original filename

        Returns:
            Configured SngChart instance
        """
        sng_filename = filename or f"{name}.sng"

        sng_file = ChartFile(
            id=file_id,
            path=sng_filename,
            size=size,
            md5=md5,
        )

        # For .sng files, local_path is the folder containing the file
        # (keeps structure consistent with other chart types)
        return cls(
            name=name,
            remote_id=file_id,
            local_path=local_base,  # .sng files go directly in base
            checksum=md5,
            sng_file=sng_file,
            files=[sng_file],  # Single file for counting
        )

    @classmethod
    def from_manifest_data_flat(cls, name: str, file_id: str, local_base: Path,
                                 size: int = 0, md5: str = "",
                                 filename: str = "") -> "SngChart":
        """
        Create a SngChart that stores the file directly in local_base.

        Use this when .sng files should be stored flat (not in subfolders).

        Args:
            name: Chart name
            file_id: Google Drive file ID
            local_base: Directory to store the .sng file
            size: File size
            md5: File checksum
            filename: Original filename

        Returns:
            Configured SngChart instance
        """
        sng_filename = filename or f"{name}.sng"

        sng_file = ChartFile(
            id=file_id,
            path=sng_filename,
            size=size,
            md5=md5,
        )

        return cls(
            name=name,
            remote_id=file_id,
            local_path=local_base,
            checksum=md5,
            sng_file=sng_file,
            files=[sng_file],
        )
