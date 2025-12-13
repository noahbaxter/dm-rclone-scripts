"""
Confirmation dialog widget.

Simple yes/no confirmation prompt.
"""

from .menu import Menu, MenuItem


class ConfirmDialog:
    """
    A simple Yes/No confirmation dialog.

    Usage:
        dialog = ConfirmDialog("Delete these files?", "This cannot be undone")
        if dialog.run():
            # User confirmed
    """

    def __init__(self, title: str, message: str = None):
        """
        Create a confirmation dialog.

        Args:
            title: The question to ask (e.g., "Are you sure?")
            message: Optional additional context shown as subtitle
        """
        self.title = title
        self.message = message or ""

    def run(self) -> bool:
        """
        Show the dialog and wait for response.

        Returns:
            True if user confirmed (Yes), False otherwise (No or cancelled)
        """
        menu = Menu(title=self.title, subtitle=self.message)

        menu.add_item(MenuItem("No", hotkey="N", value=False))
        menu.add_item(MenuItem("Yes", hotkey="Y", value=True))

        result = menu.run()
        if result is None:
            return False

        return result.value
