"""
Chart type enum for DM Chart Sync.
"""

from enum import Enum


class ChartType(Enum):
    """Types of chart formats."""
    FOLDER = "folder"  # Loose files in a folder
    ZIP = "zip"        # Compressed archive
    SNG = "sng"        # Single .sng container
