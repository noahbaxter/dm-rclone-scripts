"""
FolderChart implementation for loose file charts.

This is the most common chart type - a folder containing:
- song.ini (chart metadata)
- notes.mid or notes.chart (note data)
- song.ogg/mp3/etc (audio)
- Optional: album.png, video.mp4, etc
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .base import Chart, ChartType, ChartFile, ChartState
from ..file_ops import find_unexpected_files


@dataclass
class FolderChart(Chart):
    """
    A chart stored as loose files in a folder.

    Sync strategy:
    - Compare each file by size (and optionally checksum)
    - Download only files that are missing or changed
    - No need to delete/recreate entire folder
    """

    chart_type: ChartType = field(default=ChartType.FOLDER, init=False)

    def check_state(self) -> ChartState:
        """
        Check local state by comparing files.

        Returns:
            MISSING: Folder doesn't exist or has no files
            CURRENT: All files present with correct sizes
            OUTDATED: Some files have wrong sizes (checksums differ)
            PARTIAL: Some files missing, others present
        """
        if not self.local_path.exists():
            return ChartState.MISSING

        if not self.files:
            return ChartState.MISSING

        missing = 0
        outdated = 0
        current = 0

        for f in self.files:
            local_file = self.local_path / f.path
            if not local_file.exists():
                missing += 1
            elif f.size and local_file.stat().st_size != f.size:
                outdated += 1
            else:
                current += 1

        total = len(self.files)

        if missing == total:
            return ChartState.MISSING
        elif outdated > 0 or missing > 0:
            if current > 0:
                return ChartState.PARTIAL
            return ChartState.OUTDATED
        else:
            return ChartState.CURRENT

    def get_download_tasks(self) -> List[dict]:
        """
        Get download tasks for files that need syncing.

        Only includes files that are missing or have wrong size.
        """
        tasks = []

        for f in self.files:
            local_file = self.local_path / f.path
            needs_download = False

            if not local_file.exists():
                needs_download = True
            elif f.size and local_file.stat().st_size != f.size:
                needs_download = True

            if needs_download:
                tasks.append({
                    "id": f.id,
                    "local_path": local_file,
                    "size": f.size,
                    "md5": f.md5,
                })

        return tasks

    def needs_full_resync(self) -> bool:
        """Folder charts never need full resync - can update individual files."""
        return False

    def prepare_for_sync(self) -> None:
        """Create the folder if it doesn't exist."""
        self.local_path.mkdir(parents=True, exist_ok=True)

    def post_sync(self) -> None:
        """No cleanup needed for folder charts."""
        pass

    def get_extra_files(self) -> List[Path]:
        """
        Find local files not in the manifest.

        Returns list of paths to files that exist locally
        but aren't in the chart's file list.
        """
        expected_paths = {self.local_path / f.path for f in self.files}
        return find_unexpected_files(self.local_path, expected_paths)

    @classmethod
    def from_manifest_data(cls, name: str, folder_id: str, local_base: Path,
                           files: List[dict]) -> "FolderChart":
        """
        Create a FolderChart from manifest data.

        Args:
            name: Chart name
            folder_id: Google Drive folder ID
            local_base: Base path for local storage
            files: List of file dicts from manifest

        Returns:
            Configured FolderChart instance
        """
        chart_files = [
            ChartFile(
                id=f["id"],
                path=f["path"],
                size=f.get("size", 0),
                md5=f.get("md5", ""),
            )
            for f in files
        ]

        return cls(
            name=name,
            remote_id=folder_id,
            local_path=local_base / name,
            files=chart_files,
        )
