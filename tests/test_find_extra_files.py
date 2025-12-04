"""
Tests for find_extra_files archive detection.

Verifies that extracted archive contents aren't flagged as purgeable
when check.txt contains the correct MD5 hash.
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.sync.operations import find_extra_files


class TestArchiveDetection:
    """Tests for the check.txt archive validation in find_extra_files."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_extracted_archive_not_flagged_as_extra(self, temp_dir):
        """
        Extracted archive contents should not be flagged as extra files
        when check.txt has matching MD5.

        This is THE critical regression test. Before the fix:
        - check.txt was read without archive_name parameter
        - Multi-archive format {"archives": {...}} returned empty MD5
        - All extracted files were incorrectly flagged as extra

        After the fix:
        - archive_name is passed to read_checksum()
        - Multi-archive format is properly read
        - Extracted files are recognized as valid
        """
        # Setup: create folder structure simulating extracted archive
        base_path = temp_dir
        folder_name = "TestDrive"
        folder_path = base_path / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        # Create extracted files (what would come from archive)
        (chart_folder / "song.ini").write_text("[song]\nname=Test")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        (chart_folder / "song.ogg").write_bytes(b"audio data")

        # Create check.txt with multi-archive format (the format that broke)
        archive_name = "SomeChart.7z"
        archive_md5 = "abc123def456"
        check_data = {
            "archives": {
                archive_name: {
                    "md5": archive_md5,
                    "size": 12345
                }
            }
        }
        (chart_folder / "check.txt").write_text(json.dumps(check_data))

        # Create manifest that references this archive
        folder = {
            "name": folder_name,
            "files": [
                {
                    "path": f"Setlist/SomeChart/{archive_name}",
                    "md5": archive_md5,
                    "size": 5000
                }
            ]
        }

        # Execute: find extra files
        extras = find_extra_files(folder, base_path)

        # Assert: extracted files should NOT be flagged as extra
        extra_names = [f.name for f, _ in extras]
        assert "song.ini" not in extra_names, "song.ini was incorrectly flagged as extra"
        assert "notes.mid" not in extra_names, "notes.mid was incorrectly flagged as extra"
        assert "song.ogg" not in extra_names, "song.ogg was incorrectly flagged as extra"
        assert "check.txt" not in extra_names, "check.txt was incorrectly flagged as extra"

    def test_mismatched_md5_flagged_as_extra(self, temp_dir):
        """Files from archives with wrong MD5 should be flagged as extra."""
        base_path = temp_dir
        folder_name = "TestDrive"
        folder_path = base_path / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        # Create extracted file
        (chart_folder / "song.ini").write_text("[song]\nname=Test")

        # Create check.txt with WRONG MD5
        check_data = {
            "archives": {
                "SomeChart.7z": {
                    "md5": "wrong_md5_hash",
                    "size": 12345
                }
            }
        }
        (chart_folder / "check.txt").write_text(json.dumps(check_data))

        # Manifest has different MD5
        folder = {
            "name": folder_name,
            "files": [
                {
                    "path": "Setlist/SomeChart/SomeChart.7z",
                    "md5": "correct_md5_hash",
                    "size": 5000
                }
            ]
        }

        extras = find_extra_files(folder, base_path)

        # With mismatched MD5, extracted files SHOULD be flagged
        extra_names = [f.name for f, _ in extras]
        assert "song.ini" in extra_names, "Mismatched archive contents should be flagged"

    def test_no_check_txt_flagged_as_extra(self, temp_dir):
        """Files without check.txt should be flagged as extra."""
        base_path = temp_dir
        folder_name = "TestDrive"
        folder_path = base_path / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        # Create extracted file but NO check.txt
        (chart_folder / "song.ini").write_text("[song]\nname=Test")

        folder = {
            "name": folder_name,
            "files": [
                {
                    "path": "Setlist/SomeChart/SomeChart.7z",
                    "md5": "some_md5",
                    "size": 5000
                }
            ]
        }

        extras = find_extra_files(folder, base_path)

        extra_names = [f.name for f, _ in extras]
        assert "song.ini" in extra_names, "Files without check.txt should be flagged"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
