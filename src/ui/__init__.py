"""
User interface module.

Handles terminal UI, menus, keyboard input, and colors.
"""

from .colors import Colors, rgb, lerp_color
from .keyboard import (
    CancelInput,
    getch,
    check_esc_pressed,
    input_with_esc,
    wait_for_key,
    menu_input,
    wait_with_skip,
    KEY_UP,
    KEY_DOWN,
    KEY_LEFT,
    KEY_RIGHT,
    KEY_ENTER,
    KEY_ESC,
    KEY_BACKSPACE,
    KEY_TAB,
    KEY_SPACE,
)
from .menu import (
    Menu,
    MenuItem,
    MenuDivider,
    MenuAction,
    MenuResult,
    print_header,
)

# Note: screens imported lazily to avoid circular import with sync module


def __getattr__(name):
    """Lazy import for screens module to avoid circular imports."""
    if name in ("show_main_menu", "show_subfolder_settings", "compute_main_menu_cache", "show_confirmation", "show_oauth_prompt", "show_add_custom_folder"):
        from . import screens
        return getattr(screens, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Colors
    "Colors",
    "rgb",
    "lerp_color",
    # Keyboard
    "CancelInput",
    "getch",
    "check_esc_pressed",
    "input_with_esc",
    "wait_for_key",
    "menu_input",
    "wait_with_skip",
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_ENTER",
    "KEY_ESC",
    "KEY_BACKSPACE",
    "KEY_TAB",
    "KEY_SPACE",
    # Menu
    "Menu",
    "MenuItem",
    "MenuDivider",
    "MenuAction",
    "MenuResult",
    "print_header",
    # Screens (lazy loaded)
    "show_main_menu",
    "show_subfolder_settings",
    "compute_main_menu_cache",
    "show_confirmation",
    "show_oauth_prompt",
    "show_add_custom_folder",
]
