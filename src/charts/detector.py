"""
Chart type detection helpers.

Used by counter.py for manifest generation.
"""

# File extensions that indicate chart content
CHART_NOTE_FILES = {"notes.mid", "notes.chart"}
CHART_INI_FILES = {"song.ini"}

# Archive extensions
ZIP_EXTENSIONS = {".zip", ".rar", ".7z"}
SNG_EXTENSION = ".sng"


def is_sng_file(filename: str) -> bool:
    """Check if filename is a .sng container."""
    return filename.lower().endswith(SNG_EXTENSION)


def is_zip_file(filename: str) -> bool:
    """Check if filename is a zip/rar/7z archive."""
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in ZIP_EXTENSIONS)


def has_folder_chart_markers(filenames: set[str]) -> bool:
    """Check if a set of filenames contains folder chart markers (song.ini or notes)."""
    lower_names = {f.lower() for f in filenames}
    return bool(lower_names & CHART_INI_FILES) or bool(lower_names & CHART_NOTE_FILES)
