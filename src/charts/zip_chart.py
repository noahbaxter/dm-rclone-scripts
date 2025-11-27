"""
ZipChart implementation for compressed archive charts.

A chart distributed as a .zip file that needs to be:
1. Downloaded
2. Checksum stored (for future comparison)
3. Extracted to a folder
4. Zip deleted

On subsequent syncs:
- Compare stored checksum with remote checksum
- If different: delete folder, re-download, re-extract
"""

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .base import Chart, ChartType, ChartFile, ChartState


CHECKSUM_FILE = ".chart_checksum.json"


@dataclass
class ZipChart(Chart):
    """
    A chart stored as a zip archive.

    Sync strategy:
    - Store checksum of zip in a metadata file after extraction
    - On sync, compare remote checksum to stored checksum
    - If different, delete entire folder and re-download/extract
    """

    chart_type: ChartType = field(default=ChartType.ZIP, init=False)

    # The single zip file info
    zip_file: ChartFile = field(default=None)

    def _get_checksum_path(self) -> Path:
        """Get path to the checksum metadata file."""
        return self.local_path / CHECKSUM_FILE

    def _read_stored_checksum(self) -> str:
        """Read the stored checksum from metadata file."""
        checksum_path = self._get_checksum_path()
        if not checksum_path.exists():
            return ""

        try:
            with open(checksum_path) as f:
                data = json.load(f)
                return data.get("md5", "") or data.get("checksum", "")
        except (json.JSONDecodeError, IOError):
            return ""

    def _write_checksum(self, checksum: str) -> None:
        """Write checksum to metadata file."""
        checksum_path = self._get_checksum_path()
        self.local_path.mkdir(parents=True, exist_ok=True)

        with open(checksum_path, "w") as f:
            json.dump({
                "md5": checksum,
                "zip_name": self.zip_file.path if self.zip_file else "",
                "chart_type": "zip",
            }, f, indent=2)

    def check_state(self) -> ChartState:
        """
        Check local state by comparing checksums.

        Returns:
            MISSING: Folder doesn't exist or no checksum stored
            CURRENT: Stored checksum matches remote
            OUTDATED: Checksums differ
        """
        if not self.local_path.exists():
            return ChartState.MISSING

        stored_checksum = self._read_stored_checksum()
        if not stored_checksum:
            # Folder exists but no checksum - treat as missing
            return ChartState.MISSING

        remote_checksum = self.zip_file.md5 if self.zip_file else self.checksum
        if not remote_checksum:
            # No remote checksum available - assume current if folder exists
            return ChartState.CURRENT

        if stored_checksum == remote_checksum:
            return ChartState.CURRENT
        else:
            return ChartState.OUTDATED

    def get_download_tasks(self) -> List[dict]:
        """
        Get download task for the zip file.

        Returns single task for the zip archive.
        """
        if not self.zip_file:
            return []

        # Download to a temp location within the chart folder
        zip_path = self.local_path / f"_download_{self.zip_file.path}"

        return [{
            "id": self.zip_file.id,
            "local_path": zip_path,
            "size": self.zip_file.size,
            "md5": self.zip_file.md5,
            "is_zip": True,  # Flag for post-processing
        }]

    def needs_full_resync(self) -> bool:
        """Zip charts always need full resync if outdated."""
        state = self.check_state()
        return state in (ChartState.MISSING, ChartState.OUTDATED)

    def prepare_for_sync(self) -> None:
        """
        Prepare for sync by cleaning up if needed.

        If checksum changed, delete the entire folder to start fresh.
        """
        state = self.check_state()

        if state == ChartState.OUTDATED:
            # Delete entire folder
            if self.local_path.exists():
                shutil.rmtree(self.local_path)

        # Create folder for download
        self.local_path.mkdir(parents=True, exist_ok=True)

    def post_sync(self) -> None:
        """
        Extract zip and clean up after download.

        1. Find the downloaded zip
        2. Extract contents
        3. Save checksum
        4. Delete zip file
        """
        if not self.zip_file:
            return

        zip_path = self.local_path / f"_download_{self.zip_file.path}"
        if not zip_path.exists():
            return

        try:
            # Extract zip
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Extract to chart folder
                zf.extractall(self.local_path)

            # Save checksum
            self._write_checksum(self.zip_file.md5)

            # Delete zip
            zip_path.unlink()

        except zipfile.BadZipFile:
            # Failed to extract - delete the bad zip
            if zip_path.exists():
                zip_path.unlink()
            raise

    @classmethod
    def from_manifest_data(cls, name: str, file_id: str, local_base: Path,
                           size: int = 0, md5: str = "",
                           filename: str = "") -> "ZipChart":
        """
        Create a ZipChart from manifest data.

        Args:
            name: Chart name (usually zip filename without extension)
            file_id: Google Drive file ID
            local_base: Base path for local storage
            size: Zip file size
            md5: Zip file checksum
            filename: Original zip filename

        Returns:
            Configured ZipChart instance
        """
        zip_file = ChartFile(
            id=file_id,
            path=filename or f"{name}.zip",
            size=size,
            md5=md5,
        )

        return cls(
            name=name,
            remote_id=file_id,
            local_path=local_base / name,
            checksum=md5,
            zip_file=zip_file,
            files=[zip_file],  # Single file for counting
        )
