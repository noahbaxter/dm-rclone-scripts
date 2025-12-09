"""
Checksum file I/O for DM Chart Sync.

Handles reading and writing check.txt files that track archive state.
"""

import json
from pathlib import Path
from typing import Tuple

# Checksum file for tracking archive chart state
CHECKSUM_FILE = "check.txt"


def get_folder_size(folder_path: Path) -> int:
    """Calculate total size of all files in folder (excluding check.txt)."""
    total = 0
    for f in folder_path.rglob("*"):
        if f.is_file() and f.name != CHECKSUM_FILE:
            try:
                total += f.stat().st_size
            except Exception:
                pass
    return total


def read_checksum(folder_path: Path, archive_name: str = None) -> str:
    """
    Read stored MD5 from check.txt.

    Args:
        folder_path: Path to folder containing check.txt
        archive_name: Optional archive name to look up (for multi-archive format)

    Returns:
        MD5 string, or empty string if not found
    """
    checksum_path = folder_path / CHECKSUM_FILE
    if not checksum_path.exists():
        return ""
    try:
        with open(checksum_path) as f:
            data = json.load(f)

            # New multi-archive format
            if "archives" in data and archive_name:
                archive_data = data["archives"].get(archive_name, {})
                return archive_data.get("md5", "")

            # Old single-archive format (backwards compat)
            return data.get("md5", "")
    except (json.JSONDecodeError, IOError):
        return ""


def write_checksum(
    folder_path: Path,
    md5: str,
    archive_name: str,
    archive_size: int = 0,
    extracted_size: int = 0,
    size_novideo: int = None,
    extracted_to: str = None
):
    """
    Write MD5 and size info to check.txt.

    Uses multi-archive format that stores all archives in one file.

    Args:
        folder_path: Path to folder for check.txt
        md5: MD5 hash of the archive
        archive_name: Name of the archive file
        archive_size: Size of the archive file (download size)
        extracted_size: Size after extraction (canonical size on disk)
        size_novideo: Size after video removal (only if different from extracted_size)
        extracted_to: Name of folder contents were extracted to (if different from archive)
    """
    checksum_path = folder_path / CHECKSUM_FILE
    folder_path.mkdir(parents=True, exist_ok=True)

    # Read existing data (if any)
    existing = {}
    if checksum_path.exists():
        try:
            with open(checksum_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Migrate old format to new format if needed
    if "archives" not in existing:
        archives = {}
        # Migrate old single-archive entry if present
        if "md5" in existing and "archive" in existing:
            old_name = existing["archive"]
            archives[old_name] = {
                "md5": existing["md5"],
                "size": existing.get("size", 0),
            }
        existing = {"archives": archives}

    # Add/update this archive
    archive_data = {
        "md5": md5,
        "archive_size": archive_size,
        "size": extracted_size,
    }
    # Only store size_novideo if videos were removed and size changed
    if size_novideo is not None and size_novideo != extracted_size:
        archive_data["size_novideo"] = size_novideo
    if extracted_to:
        archive_data["extracted_to"] = extracted_to

    existing["archives"][archive_name] = archive_data

    with open(checksum_path, "w") as f:
        json.dump(existing, f, indent=2)


def read_checksum_data(folder_path: Path) -> dict:
    """
    Read full check.txt data.

    Returns dict with "archives" key containing all archive info.
    Handles both old and new formats.
    """
    checksum_path = folder_path / CHECKSUM_FILE
    if not checksum_path.exists():
        return {"archives": {}}
    try:
        with open(checksum_path) as f:
            data = json.load(f)

        # Already new format
        if "archives" in data:
            return data

        # Migrate old format on read
        if "md5" in data and "archive" in data:
            return {
                "archives": {
                    data["archive"]: {
                        "md5": data["md5"],
                        "size": data.get("size", 0),
                    }
                }
            }

        return {"archives": {}}
    except (json.JSONDecodeError, IOError):
        return {"archives": {}}


def repair_checksum_sizes(folder_path: Path) -> Tuple[int, int]:
    """
    Repair check.txt files with missing/incorrect size data.

    Scans folder for check.txt files and updates them with actual sizes
    calculated from the extracted content on disk.

    Args:
        folder_path: Base folder to scan (e.g., Sync Charts/Guitar Hero)

    Returns:
        Tuple of (repaired_count, total_checked)
    """
    repaired = 0
    checked = 0

    for checksum_file in folder_path.rglob(CHECKSUM_FILE):
        chart_folder = checksum_file.parent
        checked += 1

        try:
            with open(checksum_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        if "archives" not in data:
            continue

        modified = False
        for archive_name, archive_info in data["archives"].items():
            # Check if size is missing or zero
            current_size = archive_info.get("size", 0)
            if current_size > 0:
                continue  # Already has valid size

            # Calculate actual size from disk
            # First, try to find the extracted folder by archive stem
            archive_stem = Path(archive_name).stem
            extracted_folder = chart_folder / archive_stem

            # Also check for _download_ prefixed folder (old bug)
            download_prefixed = chart_folder / f"_download_{archive_stem}"

            # Calculate size from whichever folder exists
            if extracted_folder.exists() and extracted_folder.is_dir():
                actual_size = get_folder_size(extracted_folder)
            elif download_prefixed.exists() and download_prefixed.is_dir():
                actual_size = get_folder_size(download_prefixed)
                # Rename the folder to fix the _download_ prefix issue
                try:
                    download_prefixed.rename(extracted_folder)
                except OSError:
                    pass  # Keep original name if rename fails
            else:
                # No extracted folder found, calculate from chart folder
                # (for archives that extract flat without a subfolder)
                actual_size = get_folder_size(chart_folder)

            if actual_size > 0:
                archive_info["size"] = actual_size
                modified = True

        if modified:
            with open(checksum_file, "w") as f:
                json.dump(data, f, indent=2)
            repaired += 1

    return repaired, checked
