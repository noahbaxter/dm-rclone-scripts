"""
User settings management for DM Chart Sync.

Manages .dm-sync/settings.json - user preferences that persist across runs.
"""

import json
from pathlib import Path


class UserSettings:
    """
    Manages .dm-sync/settings.json - user preferences that persist across runs.

    Stores:
    - Drive toggle states (which drives are enabled/disabled at the top level)
    - Subfolder toggle states (which subfolders are enabled/disabled per drive)
    """

    # Drives enabled by default when no settings file exists
    DEFAULT_ENABLED_DRIVES = {
        "1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf",  # BirdmanExe Drive
        "1bqsJzbXRkmRda3qJFX3W36UD3Sg_eIVj",  # Drummer's Monthly Drive
    }

    def __init__(self, path: Path):
        self.path = path
        # Drive-level toggles: { drive_folder_id: enabled_bool }
        self.drive_toggles: dict[str, bool] = {}
        # Subfolder toggles: { drive_folder_id: { subfolder_name: enabled_bool } }
        self.subfolder_toggles: dict[str, dict[str, bool]] = {}
        # Group expanded state: { group_name: expanded_bool }
        self.group_expanded: dict[str, bool] = {}
        # Whether to delete video files from extracted archive charts
        self.delete_videos: bool = True
        # Whether user has been prompted to sign in to Google
        self.oauth_prompted: bool = False
        # Delta display mode: "size", "files", or "charts"
        self.delta_mode: str = "size"
        # Track if this is a fresh settings file (no file existed)
        self._is_new: bool = False

    @classmethod
    def load(cls, path: Path) -> "UserSettings":
        """Load user settings from file."""
        settings = cls(path)

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                settings.drive_toggles = data.get("drive_toggles", {})
                settings.subfolder_toggles = data.get("subfolder_toggles", {})
                settings.group_expanded = data.get("group_expanded", {})
                settings.delete_videos = data.get("delete_videos", True)
                settings.oauth_prompted = data.get("oauth_prompted", False)
                settings.delta_mode = data.get("delta_mode", "size")
            except (json.JSONDecodeError, IOError):
                settings._is_new = True
        else:
            settings._is_new = True

        return settings

    def save(self):
        """Save user settings to file."""
        data = {
            "drive_toggles": self.drive_toggles,
            "subfolder_toggles": self.subfolder_toggles,
            "group_expanded": self.group_expanded,
            "delete_videos": self.delete_videos,
            "oauth_prompted": self.oauth_prompted,
            "delta_mode": self.delta_mode,
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def cycle_delta_mode(self) -> str:
        """Cycle through delta display modes. Returns new mode."""
        modes = ["size", "files", "charts"]
        current_idx = modes.index(self.delta_mode) if self.delta_mode in modes else 0
        self.delta_mode = modes[(current_idx + 1) % len(modes)]
        return self.delta_mode

    def is_drive_enabled(self, drive_id: str) -> bool:
        """Check if a drive is enabled at the top level.

        For new users (no settings file), only DEFAULT_ENABLED_DRIVES are enabled.
        For existing users, any drive not explicitly set defaults to enabled.
        """
        if drive_id in self.drive_toggles:
            return self.drive_toggles[drive_id]
        # New users: only default drives enabled
        if self._is_new:
            return drive_id in self.DEFAULT_ENABLED_DRIVES
        # Existing users: default to enabled for backwards compatibility
        return True

    def set_drive_enabled(self, drive_id: str, enabled: bool):
        """Set whether a drive is enabled at the top level."""
        self.drive_toggles[drive_id] = enabled

    def toggle_drive(self, drive_id: str) -> bool:
        """Toggle a drive's enabled state. Returns the new state."""
        current = self.is_drive_enabled(drive_id)
        self.set_drive_enabled(drive_id, not current)
        return not current

    def enable_drive(self, drive_id: str):
        """Enable a drive."""
        self.set_drive_enabled(drive_id, True)

    def is_subfolder_enabled(self, drive_id: str, subfolder_name: str) -> bool:
        """Check if a subfolder is enabled (defaults to True)."""
        return self.subfolder_toggles.get(drive_id, {}).get(subfolder_name, True)

    def set_subfolder_enabled(self, drive_id: str, subfolder_name: str, enabled: bool):
        """Set whether a subfolder is enabled."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        self.subfolder_toggles[drive_id][subfolder_name] = enabled

    def toggle_subfolder(self, drive_id: str, subfolder_name: str) -> bool:
        """Toggle a subfolder's enabled state. Returns the new state."""
        current = self.is_subfolder_enabled(drive_id, subfolder_name)
        self.set_subfolder_enabled(drive_id, subfolder_name, not current)
        return not current

    def get_disabled_subfolders(self, drive_id: str) -> set[str]:
        """Get set of disabled subfolder names for a drive."""
        toggles = self.subfolder_toggles.get(drive_id, {})
        return {name for name, enabled in toggles.items() if not enabled}

    def enable_all(self, drive_id: str, subfolder_names: list[str]):
        """Enable all subfolders for a drive."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        for name in subfolder_names:
            self.subfolder_toggles[drive_id][name] = True

    def disable_all(self, drive_id: str, subfolder_names: list[str]):
        """Disable all subfolders for a drive."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        for name in subfolder_names:
            self.subfolder_toggles[drive_id][name] = False

    def is_group_expanded(self, group_name: str) -> bool:
        """Check if a group is expanded (all groups default to expanded)."""
        if group_name not in self.group_expanded:
            # Default: all groups expanded
            return True
        return self.group_expanded.get(group_name, True)

    def toggle_group_expanded(self, group_name: str) -> bool:
        """Toggle a group's expanded state. Returns the new state."""
        current = self.is_group_expanded(group_name)
        self.group_expanded[group_name] = not current
        return not current
