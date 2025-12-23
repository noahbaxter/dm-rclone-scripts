"""
OAuth prompt screen - first-run sign-in prompt.

Explains benefits of signing in and lets user choose to sign in or skip.
"""

from ..primitives import getch, clear_screen
from ..components import print_header
from ..widgets import display


class OAuthPromptScreen:
    """First-run OAuth sign-in prompt screen."""

    def run(self) -> bool:
        """Run the prompt. Returns True if user wants to sign in."""
        return show_oauth_prompt()


def show_oauth_prompt() -> bool:
    """
    Show first-run OAuth sign-in prompt.

    Returns:
        True if user wants to sign in, False to skip
    """
    clear_screen()
    print_header()
    display.auth_prompt()

    while True:
        key = getch().lower()
        if key == "y":
            return True
        elif key == "n" or key == "\x1b":
            return False
