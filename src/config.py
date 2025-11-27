"""
User configuration management for DM Chart Sync.

Handles user preferences like download path and custom folders.
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class CustomFolder:
    """A custom folder added by the user."""
    name: str
    folder_id: str
    description: str = "Custom folder added by user"


@dataclass
class UserConfig:
    """
    User configuration settings.

    Stores:
    - download_path: Where to save downloaded files
    - custom_folders: User-added folders not in the manifest
    """

    download_path: str = "Sync Charts"
    custom_folders: list = field(default_factory=list)

    _path: Optional[Path] = field(default=None, repr=False)

    CONFIG_FILENAME = "dm_sync_config.json"

    @classmethod
    def get_app_dir(cls) -> Path:
        """Get the directory where the app is located."""
        if getattr(sys, "frozen", False):
            # Running as compiled exe
            return Path(sys.executable).parent
        else:
            # Running as script
            return Path(__file__).parent.parent

    @classmethod
    def get_default_path(cls) -> Path:
        """Get the default config file path (next to executable or script)."""
        return cls.get_app_dir() / cls.CONFIG_FILENAME

    def resolve_download_path(self) -> Path:
        """
        Resolve the download path to an absolute path.

        - Expands ~ to home directory
        - Resolves relative paths relative to the app directory
        """
        path = Path(self.download_path).expanduser()
        if not path.is_absolute():
            path = self.get_app_dir() / path
        return path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "UserConfig":
        """
        Load configuration from file.

        Args:
            path: Path to config file (uses default if not specified)

        Returns:
            Loaded UserConfig instance
        """
        config_path = path or cls.get_default_path()
        config = cls(_path=config_path)

        if config_path.exists():
            try:
                with open(config_path) as f:
                    data = json.load(f)

                config.download_path = data.get("download_path", config.download_path)
                config.custom_folders = [
                    CustomFolder(
                        name=f.get("name", ""),
                        folder_id=f.get("folder_id", ""),
                        description=f.get("description", ""),
                    )
                    for f in data.get("custom_folders", [])
                ]
            except (json.JSONDecodeError, IOError):
                pass

        return config

    def save(self):
        """Save configuration to file."""
        if not self._path:
            self._path = self.get_default_path()

        data = {
            "download_path": self.download_path,
            "custom_folders": [
                {
                    "name": f.name,
                    "folder_id": f.folder_id,
                    "description": f.description,
                }
                for f in self.custom_folders
            ],
        }

        with open(self._path, "w") as f:
            json.dump(data, f, indent=2)

    def add_custom_folder(self, name: str, folder_id: str, description: str = ""):
        """Add a custom folder."""
        # Check for duplicates
        for f in self.custom_folders:
            if f.folder_id == folder_id:
                return False

        self.custom_folders.append(CustomFolder(
            name=name,
            folder_id=folder_id,
            description=description or "Custom folder added by user",
        ))
        return True

    def remove_custom_folder(self, folder_id: str) -> bool:
        """Remove a custom folder by ID."""
        for i, f in enumerate(self.custom_folders):
            if f.folder_id == folder_id:
                self.custom_folders.pop(i)
                return True
        return False

    def get_custom_folder(self, folder_id: str) -> Optional[CustomFolder]:
        """Get a custom folder by ID."""
        for f in self.custom_folders:
            if f.folder_id == folder_id:
                return f
        return None
