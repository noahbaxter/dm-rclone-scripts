"""
Add custom folder screen - input flow for adding Google Drive folders.

Prompts user for folder URL/ID, validates it, and returns folder info.
"""

from typing import TYPE_CHECKING

from src.drive.utils import parse_drive_folder_url
from ..primitives import clear_screen, input_with_esc, CancelInput, wait_with_skip
from ..components import print_header
from ..widgets import display

if TYPE_CHECKING:
    from src.drive import DriveClient
    from src.drive.auth import AuthManager


class AddFolderScreen:
    """Screen for adding a custom Google Drive folder."""

    def __init__(self, client: "DriveClient", auth: "AuthManager" = None):
        self.client = client
        self.auth = auth

    def run(self) -> tuple[str | None, str | None]:
        """Run the screen. Returns (folder_id, folder_name) or (None, None)."""
        return show_add_custom_folder(self.client, self.auth)


def show_add_custom_folder(client, auth=None) -> tuple[str | None, str | None]:
    """
    Show the Add Custom Folder screen.

    Args:
        client: DriveClient instance with user's OAuth token
        auth: AuthManager instance (reserved for future use)

    Returns:
        Tuple of (folder_id, folder_name) if successful, (None, None) if cancelled
    """
    clear_screen()
    print_header()
    display.add_folder_prompt()

    try:
        url_input = input_with_esc("  URL or ID: ")
    except CancelInput:
        return None, None

    if not url_input.strip():
        print("\n  No URL entered.")
        wait_with_skip(2)
        return None, None

    folder_id, error = parse_drive_folder_url(url_input)
    if not folder_id:
        display.add_folder_invalid_url(error)
        wait_with_skip(3)
        return None, None

    print("\n  Checking folder access...")

    is_valid, folder_name = client.validate_folder(folder_id)

    if not is_valid:
        display.add_folder_access_denied()
        wait_with_skip(3)
        return None, None

    display.add_folder_found(folder_name)
    wait_with_skip(1)

    return folder_id, folder_name
