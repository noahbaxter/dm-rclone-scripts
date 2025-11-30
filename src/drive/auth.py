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


class UserOAuthManager:
    """
    OAuth manager for end-user authentication using embedded credentials.

    Unlike OAuthManager (for admin use), this class:
    - Uses embedded OAuth client credentials (no credentials.json needed)
    - Stores user token at .dm-sync/token.json
    - Provides explicit sign_in/sign_out methods
    - Designed for optional user authentication to reduce rate limits
    """

    def __init__(self, token_path: Optional[Path] = None):
        """
        Initialize user OAuth manager.

        Args:
            token_path: Path to save/load user token (default: .dm-sync/token.json)
        """
        if token_path is None:
            from ..paths import get_token_path
            token_path = get_token_path()
        self.token_path = token_path
        self._credentials: Optional[Credentials] = None

    @property
    def is_available(self) -> bool:
        """Check if OAuth libraries are available."""
        return OAUTH_AVAILABLE

    @property
    def is_signed_in(self) -> bool:
        """Check if user has a valid saved token."""
        if not OAUTH_AVAILABLE:
            return False

        if not self.token_path.exists():
            return False

        # Try to load and validate token
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path))
            # Valid if not expired, or if we can refresh
            return creds.valid or (creds.expired and creds.refresh_token)
        except Exception:
            return False

    def get_credentials(self) -> Optional[Credentials]:
        """
        Load existing credentials, refresh if needed.

        Returns:
            Credentials object or None if not signed in
        """
        if not OAUTH_AVAILABLE:
            return None

        if not self.token_path.exists():
            return None

        creds = None

        # Load existing token
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path))
        except Exception:
            return None

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
            except Exception:
                # Refresh failed - token is invalid
                return None

        if creds and creds.valid:
            self._credentials = creds
            return creds

        return None

    def get_token(self) -> Optional[str]:
        """
        Get the access token string.

        Returns:
            Access token string or None if not signed in
        """
        creds = self.get_credentials()
        if creds:
            return creds.token
        return None

    def sign_in(self) -> bool:
        """
        Interactive sign-in flow. Opens browser for user to authorize.

        Returns:
            True if sign-in successful, False otherwise
        """
        if not OAUTH_AVAILABLE:
            return False

        # Import credentials from constants
        from ..constants import (
            USER_OAUTH_CLIENT_ID,
            USER_OAUTH_CLIENT_SECRET,
            USER_OAUTH_SCOPES,
        )

        # Build client config dict (same format as credentials.json)
        client_config = {
            "installed": {
                "client_id": USER_OAUTH_CLIENT_ID,
                "client_secret": USER_OAUTH_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }

        try:
            flow = InstalledAppFlow.from_client_config(client_config, USER_OAUTH_SCOPES)
            creds = flow.run_local_server(port=0)

            if creds:
                self._save_token(creds)
                self._credentials = creds
                return True
        except Exception as e:
            print(f"  Sign-in error: {e}")

        return False

    def sign_out(self):
        """Remove saved token (sign out)."""
        if self.token_path.exists():
            try:
                self.token_path.unlink()
            except Exception:
                pass
        self._credentials = None

    def get_user_email(self) -> Optional[str]:
        """
        Get signed-in user's email for display.

        Returns:
            Email string or None if not available
        """
        if not self._credentials:
            self.get_credentials()

        if self._credentials:
            # The token file stores the email in the 'account' field if available
            # Otherwise we'd need to make an API call to get it
            try:
                import json
                with open(self.token_path) as f:
                    data = json.load(f)
                    return data.get("account") or None
            except Exception:
                pass

        return None

    def _save_token(self, creds: Credentials):
        """Save credentials to token file."""
        try:
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())
        except Exception:
            pass
