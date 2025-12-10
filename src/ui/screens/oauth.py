"""
OAuth prompt screen - first-run sign-in prompt.

Explains benefits of signing in and lets user choose to sign in or skip.
"""

from ..primitives import getch, clear_screen, Colors
from ..components import print_header


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
    print()
    print("  Sign in to Google for faster downloads?")
    print()
    print("  Signing in gives you your own download quota,")
    print("  which means fewer rate limits and faster syncs.")
    print()
    print("  Your Google account is only used to download files.")
    print("  We never upload, modify, or access anything else.")
    print()
    print("  [Y] Sign in (recommended)")
    print("  [N] Skip for now")
    print()

    while True:
        key = getch().lower()
        if key == "y":
            return True
        elif key == "n" or key == "\x1b":
            return False
