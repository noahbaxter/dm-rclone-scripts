"""
Chart type detection and factory functions.

Detects chart type from:
- File extensions in manifest
- Folder contents
- Explicit type markers in manifest
"""

from pathlib import Path
from typing import List, Optional, Union

from .base import Chart, ChartType, ChartFile
from .folder_chart import FolderChart
from .zip_chart import ZipChart
from .sng_chart import SngChart


# File extensions that indicate chart content
CHART_NOTE_FILES = {"notes.mid", "notes.chart"}
CHART_INI_FILES = {"song.ini"}
CHART_AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".opus", ".flac"}

# Archive extensions
ZIP_EXTENSIONS = {".zip", ".rar", ".7z"}
SNG_EXTENSION = ".sng"


def detect_chart_type(files: List[dict]) -> ChartType:
    """
    Detect chart type from a list of files.

    Args:
        files: List of file dicts with 'path' key

    Returns:
        Detected ChartType
    """
    if not files:
        return ChartType.FOLDER  # Default

    # Check for single file cases first
    if len(files) == 1:
        filename = files[0].get("path", "").lower()

        # .sng file
        if filename.endswith(SNG_EXTENSION):
            return ChartType.SNG

        # Zip archive
        for ext in ZIP_EXTENSIONS:
            if filename.endswith(ext):
                return ChartType.ZIP

    # Check if any file indicates this is an archive
    for f in files:
        filename = f.get("path", "").lower()

        if filename.endswith(SNG_EXTENSION):
            return ChartType.SNG

        for ext in ZIP_EXTENSIONS:
            if filename.endswith(ext):
                return ChartType.ZIP

    # Default: folder chart with loose files
    return ChartType.FOLDER


def detect_chart_type_from_folder(folder_path: Path) -> ChartType:
    """
    Detect chart type from local folder contents.

    Args:
        folder_path: Path to the chart folder

    Returns:
        Detected ChartType
    """
    if not folder_path.exists():
        return ChartType.FOLDER

    files = list(folder_path.iterdir())

    # Single .sng file
    sng_files = [f for f in files if f.suffix.lower() == SNG_EXTENSION]
    if sng_files:
        return ChartType.SNG

    # Zip file present (shouldn't happen normally, but might during download)
    zip_files = [f for f in files if f.suffix.lower() in ZIP_EXTENSIONS]
    if zip_files:
        return ChartType.ZIP

    # Check for chart markers (song.ini, notes.*)
    has_ini = any(f.name.lower() in CHART_INI_FILES for f in files)
    has_notes = any(f.name.lower() in CHART_NOTE_FILES for f in files)

    if has_ini or has_notes:
        return ChartType.FOLDER

    # Default
    return ChartType.FOLDER


def create_chart(
    name: str,
    remote_id: str,
    local_base: Path,
    files: Optional[List[dict]] = None,
    chart_type: Optional[ChartType] = None,
    checksum: str = "",
) -> Chart:
    """
    Factory function to create the appropriate Chart type.

    Args:
        name: Chart name
        remote_id: Google Drive folder/file ID
        local_base: Base path for local storage
        files: List of file dicts from manifest (optional)
        chart_type: Explicit chart type (auto-detected if not provided)
        checksum: Checksum for zip/sng types

    Returns:
        Appropriate Chart subclass instance
    """
    files = files or []

    # Detect type if not specified
    if chart_type is None:
        chart_type = detect_chart_type(files)

    # Create appropriate chart type
    if chart_type == ChartType.SNG:
        if files:
            f = files[0]
            return SngChart.from_manifest_data(
                name=name,
                file_id=f.get("id", remote_id),
                local_base=local_base,
                size=f.get("size", 0),
                md5=f.get("md5", checksum),
                filename=f.get("path", ""),
            )
        else:
            return SngChart.from_manifest_data(
                name=name,
                file_id=remote_id,
                local_base=local_base,
                md5=checksum,
            )

    elif chart_type == ChartType.ZIP:
        if files:
            f = files[0]
            return ZipChart.from_manifest_data(
                name=name,
                file_id=f.get("id", remote_id),
                local_base=local_base,
                size=f.get("size", 0),
                md5=f.get("md5", checksum),
                filename=f.get("path", ""),
            )
        else:
            return ZipChart.from_manifest_data(
                name=name,
                file_id=remote_id,
                local_base=local_base,
                md5=checksum,
            )

    else:  # FOLDER
        return FolderChart.from_manifest_data(
            name=name,
            folder_id=remote_id,
            local_base=local_base,
            files=files,
        )


def create_charts_from_manifest(
    folder_name: str,
    folder_id: str,
    local_base: Path,
    manifest_files: List[dict],
) -> List[Chart]:
    """
    Create Chart objects from manifest data.

    This handles the case where a manifest folder contains multiple charts
    (e.g., a folder with many .sng files or many subfolders).

    Args:
        folder_name: Name of the manifest folder
        folder_id: Google Drive folder ID
        local_base: Base path for local storage
        manifest_files: List of all files in the manifest

    Returns:
        List of Chart objects
    """
    charts = []

    # Group files by their immediate parent folder
    # This handles nested folder structures
    folders_to_files = {}
    standalone_files = []

    for f in manifest_files:
        path = f.get("path", "")
        parts = Path(path).parts

        if len(parts) == 1:
            # File in root - standalone
            standalone_files.append(f)
        else:
            # File in subfolder - group by first folder
            subfolder = parts[0]
            if subfolder not in folders_to_files:
                folders_to_files[subfolder] = []
            # Adjust path to be relative to subfolder
            f_copy = f.copy()
            f_copy["path"] = str(Path(*parts[1:]))
            folders_to_files[subfolder].append(f_copy)

    # Create charts for each subfolder
    for subfolder, files in folders_to_files.items():
        chart = create_chart(
            name=subfolder,
            remote_id=folder_id,  # Parent folder ID (might need per-folder IDs)
            local_base=local_base / folder_name,
            files=files,
        )
        charts.append(chart)

    # Handle standalone files (likely .sng files in root)
    for f in standalone_files:
        filename = f.get("path", "")
        name = Path(filename).stem

        chart = create_chart(
            name=name,
            remote_id=f.get("id", ""),
            local_base=local_base / folder_name,
            files=[f],
        )
        charts.append(chart)

    # If no subfolders and no standalone files, treat entire folder as one chart
    if not charts and manifest_files:
        chart = create_chart(
            name=folder_name,
            remote_id=folder_id,
            local_base=local_base,
            files=manifest_files,
        )
        charts.append(chart)

    return charts


def is_valid_chart_folder(files: List[dict]) -> bool:
    """
    Check if a list of files represents a valid chart.

    A valid chart has either:
    - A .sng file
    - A .zip file
    - song.ini + notes.mid/chart

    Args:
        files: List of file dicts

    Returns:
        True if this looks like a valid chart
    """
    filenames = {Path(f.get("path", "")).name.lower() for f in files}

    # .sng file
    if any(name.endswith(SNG_EXTENSION) for name in filenames):
        return True

    # .zip file
    if any(any(name.endswith(ext) for ext in ZIP_EXTENSIONS) for name in filenames):
        return True

    # Traditional chart files
    has_ini = bool(filenames & CHART_INI_FILES)
    has_notes = bool(filenames & CHART_NOTE_FILES)

    return has_ini and has_notes
