"""
User interface module.

Organized into layers:
- primitives/: Terminal I/O (keyboard, colors, terminal control)
- components/: Visual building blocks (box, header, formatting)
- widgets/: Interactive reusable pieces (menu, confirm, progress)
- screens/: Full-page views (home, drive_config, oauth, add_folder)
"""

# Re-export commonly used items for convenience
from .primitives import (
    # Terminal
    clear_screen,
    get_terminal_width,
    print_progress,
    # Keyboard
    getch,
    input_with_esc,
    wait_for_key,
    wait_with_skip,
    CancelInput,
    KEY_UP,
    KEY_DOWN,
    KEY_ENTER,
    KEY_ESC,
    KEY_SPACE,
    # Colors
    Colors,
    rgb,
)
from .components import (
    print_header,
    strip_ansi,
    calc_percent,
    format_delta,
    format_status_line,
    format_home_item,
    format_setlist_item,
    format_drive_status,
    format_purge_tree,
)
from .widgets import (
    Menu,
    MenuItem,
    MenuDivider,
    MenuGroupHeader,
    MenuAction,
    MenuResult,
    ConfirmDialog,
    FolderProgress,
)
from .screens import (
    HomeScreen,
    MainMenuCache,
    compute_main_menu_cache,
    show_main_menu,
    DriveConfigScreen,
    show_subfolder_settings,
    OAuthPromptScreen,
    show_oauth_prompt,
    AddFolderScreen,
    show_add_custom_folder,
)

# Backwards compatibility - show_confirmation is now ConfirmDialog
def show_confirmation(title: str, message: str = None) -> bool:
    """Show a Yes/No confirmation dialog."""
    return ConfirmDialog(title, message).run()

__all__ = [
    # Primitives
    "clear_screen",
    "get_terminal_width",
    "print_progress",
    "getch",
    "input_with_esc",
    "wait_for_key",
    "wait_with_skip",
    "CancelInput",
    "KEY_UP",
    "KEY_DOWN",
    "KEY_ENTER",
    "KEY_ESC",
    "KEY_SPACE",
    "Colors",
    "rgb",
    # Components
    "print_header",
    "strip_ansi",
    "calc_percent",
    "format_delta",
    "format_status_line",
    "format_home_item",
    "format_setlist_item",
    "format_drive_status",
    "format_purge_tree",
    # Widgets
    "Menu",
    "MenuItem",
    "MenuDivider",
    "MenuGroupHeader",
    "MenuAction",
    "MenuResult",
    "ConfirmDialog",
    "FolderProgress",
    # Screens
    "HomeScreen",
    "MainMenuCache",
    "compute_main_menu_cache",
    "show_main_menu",
    "DriveConfigScreen",
    "show_subfolder_settings",
    "OAuthPromptScreen",
    "show_oauth_prompt",
    "AddFolderScreen",
    "show_add_custom_folder",
    "show_confirmation",
]
