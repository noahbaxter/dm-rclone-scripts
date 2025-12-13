"""
Full-screen interactive views.

Each screen is a class that manages its own render loop and user interaction.
"""

from .home import HomeScreen, MainMenuCache, compute_main_menu_cache, show_main_menu
from .drive_config import DriveConfigScreen, show_subfolder_settings
from .oauth import OAuthPromptScreen, show_oauth_prompt
from .add_folder import AddFolderScreen, show_add_custom_folder

__all__ = [
    # Home screen
    "HomeScreen",
    "MainMenuCache",
    "compute_main_menu_cache",
    "show_main_menu",
    # Drive config
    "DriveConfigScreen",
    "show_subfolder_settings",
    # OAuth
    "OAuthPromptScreen",
    "show_oauth_prompt",
    # Add folder
    "AddFolderScreen",
    "show_add_custom_folder",
]
