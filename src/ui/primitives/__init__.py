"""
Terminal I/O primitives.

Low-level terminal control, keyboard input, and color handling.
"""

from .terminal import (
    set_terminal_size,
    clear_screen,
    get_terminal_width,
    print_progress,
    print_long_path_warning,
)
from .keyboard_input import (
    CancelInput,
    raw_terminal,
    cbreak_noecho,
    getch,
    check_esc_pressed,
    input_with_esc,
    wait_for_key,
    menu_input,
    flush_input,
    wait_with_skip,
    KEY_UP,
    KEY_DOWN,
    KEY_LEFT,
    KEY_RIGHT,
    KEY_PAGE_UP,
    KEY_PAGE_DOWN,
    KEY_ENTER,
    KEY_ESC,
    KEY_BACKSPACE,
    KEY_TAB,
    KEY_SPACE,
)
from .colors import (
    Colors,
    rgb,
    lerp_color,
    GRADIENT_COLORS,
    get_gradient_color,
)

__all__ = [
    # Terminal
    "set_terminal_size",
    "clear_screen",
    "get_terminal_width",
    "print_progress",
    "print_long_path_warning",
    # Keyboard input
    "CancelInput",
    "raw_terminal",
    "cbreak_noecho",
    "getch",
    "check_esc_pressed",
    "input_with_esc",
    "wait_for_key",
    "menu_input",
    "flush_input",
    "wait_with_skip",
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_PAGE_UP",
    "KEY_PAGE_DOWN",
    "KEY_ENTER",
    "KEY_ESC",
    "KEY_BACKSPACE",
    "KEY_TAB",
    "KEY_SPACE",
    # Colors
    "Colors",
    "rgb",
    "lerp_color",
    "GRADIENT_COLORS",
    "get_gradient_color",
]
