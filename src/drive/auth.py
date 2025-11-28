"""
OAuth authentication manager for DM Chart Sync.

Handles Google OAuth 2.0 flow for the Changes API.
"""

import sys
from pathlib import Path
from typing import Optional

# OAuth imports are optional (only needed for admin script)
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False


class OAuthManager:
    """
    Manages OAuth 2.0 authentication for Google Drive.

    The Changes API requires OAuth (not just an API key), so this class
    handles the authentication flow for admin operations.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(
        self,
        credentials_path: Optional[Path] = None,
        token_path: Optional[Path] = None,
    ):
        """
        Initialize OAuth manager.

        Args:
            credentials_path: Path to OAuth credentials JSON
            token_path: Path to save/load token
        """
        base_path = self._get_base_path()
        self.credentials_path = credentials_path or base_path / "credentials.json"
        self.token_path = token_path or base_path / "token.json"
        self._credentials: Optional[Credentials] = None

    @staticmethod
    def _get_base_path() -> Path:
        """Get base path for credential files (for local dev)."""
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        # Look in repo root for local credential files
        return Path(__file__).parent.parent.parent

    @property
    def is_available(self) -> bool:
        """Check if OAuth libraries are available."""
        return OAUTH_AVAILABLE

    @property
    def is_configured(self) -> bool:
        """Check if OAuth credentials or token are available."""
        return self.credentials_path.exists() or self.token_path.exists()

    @property
    def has_token(self) -> bool:
        """Check if we have a saved token."""
        return self.token_path.exists()

    def get_credentials(self) -> Optional[Credentials]:
        """
        Get or refresh OAuth credentials.

        Returns:
            Credentials object or None if not available
        """
        if not OAUTH_AVAILABLE:
            return None

        creds = None

        # Try to load existing token
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path),
                    self.SCOPES
                )
            except Exception:
                pass

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        # Get new credentials via interactive flow if needed (requires credentials.json)
        if (not creds or not creds.valid) and self.credentials_path.exists():
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path),
                    self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"OAuth error: {e}")
                return None

        # Save token for next time
        if creds:
            self._save_token(creds)
            self._credentials = creds

        return creds

    def _save_token(self, creds: Credentials):
        """Save credentials to token file."""
        try:
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())
        except Exception:
            pass

    def get_token(self) -> Optional[str]:
        """
        Get the access token string.

        Returns:
            Access token string or None
        """
        creds = self.get_credentials()
        if creds:
            return creds.token
        return None

    def clear_token(self):
        """Remove saved token (force re-authentication)."""
        if self.token_path.exists():
            self.token_path.unlink()
        self._credentials = None
