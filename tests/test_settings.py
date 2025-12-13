"""
Tests for user settings management.

Tests UserSettings class - drive toggles, subfolder toggles, persistence.
"""

import tempfile
from pathlib import Path

import pytest

from src.config.settings import UserSettings


class TestUserSettingsDefaults:
    """Tests for UserSettings default behavior."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_new_user_default_drives_only(self, temp_dir):
        """New users (no settings file) only have default drives enabled."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # Default drives should be enabled
        assert settings.is_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf")  # BirdmanExe
        assert settings.is_drive_enabled("1bqsJzbXRkmRda3qJFX3W36UD3Sg_eIVj")  # Drummer's Monthly

        # Non-default drives should be disabled
        assert not settings.is_drive_enabled("some_other_drive_id")

    def test_existing_user_all_drives_enabled(self, temp_dir):
        """Existing users (have settings file) default all drives to enabled."""
        # Create empty settings file
        settings_path = temp_dir / "settings.json"
        settings_path.write_text("{}")

        settings = UserSettings.load(settings_path)

        # Any drive not explicitly toggled should be enabled
        assert settings.is_drive_enabled("any_drive_id")
        assert settings.is_drive_enabled("another_drive")

    def test_explicit_toggle_respected(self, temp_dir):
        """Explicit drive toggles override defaults."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # Explicitly disable a default drive
        settings.set_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf", False)
        assert not settings.is_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf")

        # Explicitly enable a non-default drive
        settings.set_drive_enabled("custom_drive", True)
        assert settings.is_drive_enabled("custom_drive")

    def test_toggle_drive_returns_new_state(self, temp_dir):
        """toggle_drive() returns the new enabled state."""
        settings_path = temp_dir / "settings.json"
        settings_path.write_text("{}")  # Existing user, all enabled by default
        settings = UserSettings.load(settings_path)

        # First toggle disables
        new_state = settings.toggle_drive("test_drive")
        assert new_state is False
        assert not settings.is_drive_enabled("test_drive")

        # Second toggle enables
        new_state = settings.toggle_drive("test_drive")
        assert new_state is True
        assert settings.is_drive_enabled("test_drive")


class TestSubfolderToggles:
    """Tests for subfolder enable/disable."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_subfolders_default_enabled(self, temp_dir):
        """Subfolders default to enabled."""
        settings = UserSettings.load(temp_dir / "settings.json")
        assert settings.is_subfolder_enabled("any_drive", "any_setlist")

    def test_disabled_subfolders_returned(self, temp_dir):
        """get_disabled_subfolders returns only disabled ones."""
        settings = UserSettings.load(temp_dir / "settings.json")
        settings.set_subfolder_enabled("drive1", "setlist1", False)
        settings.set_subfolder_enabled("drive1", "setlist2", True)
        settings.set_subfolder_enabled("drive1", "setlist3", False)

        disabled = settings.get_disabled_subfolders("drive1")
        assert disabled == {"setlist1", "setlist3"}

    def test_disabled_subfolders_empty_for_new_drive(self, temp_dir):
        """get_disabled_subfolders returns empty set for drives with no toggles."""
        settings = UserSettings.load(temp_dir / "settings.json")
        disabled = settings.get_disabled_subfolders("unknown_drive")
        assert disabled == set()

    def test_toggle_subfolder_returns_new_state(self, temp_dir):
        """toggle_subfolder() returns the new enabled state."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # First toggle disables (was enabled by default)
        new_state = settings.toggle_subfolder("drive1", "setlist1")
        assert new_state is False

        # Second toggle enables
        new_state = settings.toggle_subfolder("drive1", "setlist1")
        assert new_state is True

    def test_enable_all_subfolders(self, temp_dir):
        """enable_all() enables multiple subfolders at once."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # Disable some first
        settings.set_subfolder_enabled("drive1", "setlist1", False)
        settings.set_subfolder_enabled("drive1", "setlist2", False)

        # Enable all
        settings.enable_all("drive1", ["setlist1", "setlist2", "setlist3"])

        assert settings.is_subfolder_enabled("drive1", "setlist1")
        assert settings.is_subfolder_enabled("drive1", "setlist2")
        assert settings.is_subfolder_enabled("drive1", "setlist3")

    def test_disable_all_subfolders(self, temp_dir):
        """disable_all() disables multiple subfolders at once."""
        settings = UserSettings.load(temp_dir / "settings.json")

        settings.disable_all("drive1", ["setlist1", "setlist2", "setlist3"])

        assert not settings.is_subfolder_enabled("drive1", "setlist1")
        assert not settings.is_subfolder_enabled("drive1", "setlist2")
        assert not settings.is_subfolder_enabled("drive1", "setlist3")


class TestSettingsPersistence:
    """Tests for settings file persistence."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_save_and_load(self, temp_dir):
        """Settings persist across save/load cycle."""
        settings_path = temp_dir / "settings.json"

        # Create and configure
        settings = UserSettings.load(settings_path)
        settings.set_drive_enabled("drive1", False)
        settings.set_subfolder_enabled("drive2", "setlist1", False)
        settings.delete_videos = False
        settings.save()

        # Load fresh
        settings2 = UserSettings.load(settings_path)
        assert not settings2.is_drive_enabled("drive1")
        assert not settings2.is_subfolder_enabled("drive2", "setlist1")
        assert settings2.delete_videos is False

    def test_delete_videos_defaults_true(self, temp_dir):
        """delete_videos defaults to True."""
        settings = UserSettings.load(temp_dir / "settings.json")
        assert settings.delete_videos is True

    def test_oauth_prompted_persists(self, temp_dir):
        """oauth_prompted flag persists."""
        settings_path = temp_dir / "settings.json"

        settings = UserSettings.load(settings_path)
        assert settings.oauth_prompted is False

        settings.oauth_prompted = True
        settings.save()

        settings2 = UserSettings.load(settings_path)
        assert settings2.oauth_prompted is True

    def test_corrupted_file_treated_as_new(self, temp_dir):
        """Corrupted JSON file treated as new user."""
        settings_path = temp_dir / "settings.json"
        settings_path.write_text("not valid json {{{")

        settings = UserSettings.load(settings_path)

        # Should behave like new user (only default drives enabled)
        assert settings.is_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf")
        assert not settings.is_drive_enabled("random_drive")


class TestGroupExpanded:
    """Tests for group expanded state."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_groups_default_expanded(self, temp_dir):
        """Groups default to expanded."""
        settings = UserSettings.load(temp_dir / "settings.json")
        assert settings.is_group_expanded("any_group")
        assert settings.is_group_expanded("another_group")

    def test_toggle_group_expanded(self, temp_dir):
        """toggle_group_expanded() toggles and returns new state."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # First toggle collapses (was expanded by default)
        new_state = settings.toggle_group_expanded("test_group")
        assert new_state is False
        assert not settings.is_group_expanded("test_group")

        # Second toggle expands
        new_state = settings.toggle_group_expanded("test_group")
        assert new_state is True
        assert settings.is_group_expanded("test_group")

    def test_group_state_persists(self, temp_dir):
        """Group expanded state persists."""
        settings_path = temp_dir / "settings.json"

        settings = UserSettings.load(settings_path)
        settings.toggle_group_expanded("collapsed_group")
        settings.save()

        settings2 = UserSettings.load(settings_path)
        assert not settings2.is_group_expanded("collapsed_group")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
