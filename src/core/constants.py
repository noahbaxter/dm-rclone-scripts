"""
Shared constants for DM Chart Sync.
"""

# Files that indicate a folder is a chart
CHART_MARKERS = {"song.ini", "notes.mid", "notes.chart"}

# OAuth client for user authentication (read-only scope)
# Desktop apps can't truly keep secrets - this is expected by Google
# Users authenticate with their own Google account to get their own download quota
USER_OAUTH_CLIENT_ID = "296168312762-8fvncs1v05glesaacd7posf6jo2ijsp1.apps.googleusercontent.com"
USER_OAUTH_CLIENT_SECRET = "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"
USER_OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Archive extensions that contain charts
CHART_ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}

# Video file extensions to delete from extracted charts
VIDEO_EXTENSIONS = {".mp4", ".avi", ".webm", ".mkv", ".mov"}
