"""
Interactive UI widgets.

Reusable interactive components with their own input handling and state.
"""

from .menu import (
    Menu,
    MenuItem,
    MenuDivider,
    MenuGroupHeader,
    MenuAction,
    MenuResult,
    check_resize,
)
from .confirm import ConfirmDialog
from .progress import FolderProgress
from . import sync_display as display

__all__ = [
    # Menu
    "Menu",
    "MenuItem",
    "MenuDivider",
    "MenuGroupHeader",
    "MenuAction",
    "MenuResult",
    "check_resize",
    # Confirm
    "ConfirmDialog",
    # Progress
    "FolderProgress",
    # Display
    "display",
]
