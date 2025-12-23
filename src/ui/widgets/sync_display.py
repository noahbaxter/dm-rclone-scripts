"""
Centralized display functions for formatted output.

Any output with color codes or complex formatting belongs here.
Plain text prints can be inlined at the call site.

Usage:
    from src.ui.widgets import display
    display.folder_complete(downloaded, bytes, duration, errors)
"""

from ..primitives.colors import Colors
from ...core.formatting import format_size, format_duration, format_speed

_c = Colors


# === Network errors ===

def error_offline(message: str):
    print(f"\n{_c.RED}Error:{_c.RESET} {message}")
    print("This app requires an internet connection to download charts.")
    print("Please check your connection and try again.\n")

def error_manifest_http(status_code: int):
    print(f"{_c.DIM}Warning: Failed to fetch manifest (HTTP {status_code}){_c.RESET}")

def error_manifest_timeout():
    print(f"{_c.DIM}Warning: Manifest fetch timed out{_c.RESET}")

def error_manifest_generic(error: str):
    print(f"{_c.DIM}Warning: Manifest fetch error: {error}{_c.RESET}")

def error_no_local_manifest():
    print(f"{_c.RED}Error:{_c.RESET} Local manifest not found.\n")


# === Auth/OAuth messages ===

def auth_prompt():
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

def auth_opening_browser():
    print("\n  Opening browser for Google sign-in...")
    print("  (If browser doesn't open, check your terminal)")
    print()

def auth_required_custom_folders():
    print("\n  Please sign in to Google first to add custom folders.")
    print("  Custom folders require access to your Google Drive.")

def auth_required_scan():
    print("\n  Cannot scan custom folders: not signed in to Google.")
    print("  Sign in first to download from custom folders.")

def auth_expired_warning(failure_count: int):
    print()
    print(f"  {failure_count} files failed - your sign-in may have expired.")
    print("  Try signing out and back in, then sync again.")
    print()


# === Custom folder messages ===

def add_folder_prompt():
    print()
    print("  Add Custom Folder")
    print()
    print("  Paste a Google Drive folder URL or ID.")
    print("  The folder must be shared (anyone with link) or in your Drive.")
    print()
    print("  Example: https://drive.google.com/drive/folders/abc123...")
    print()
    print(f"  {_c.DIM}Press ESC to cancel{_c.RESET}")
    print()

def add_folder_invalid_url(error: str):
    print(f"\n  {_c.BOLD}{error}{_c.RESET}")
    print("  Please use a Google Drive folder link like:")
    print("  https://drive.google.com/drive/folders/abc123...")

def add_folder_access_denied():
    print(f"\n  {_c.BOLD}Could not access folder.{_c.RESET}")
    print("  Make sure the folder is shared or you have access.")

def add_folder_found(folder_name: str):
    print(f"  Found: {_c.BOLD}{folder_name}{_c.RESET}")


# === Scan messages ===

def scan_header(folder_name: str):
    print()
    print("=" * 50)
    print(f"Scanning: {folder_name}")
    print("=" * 50)

def scan_custom_folders_header():
    print()
    print("=" * 50)
    print("Scanning custom folders...")
    print("=" * 50)

def scan_complete_header():
    print()
    print("=" * 50)
    print("Scan complete. Starting download...")
    print("=" * 50)

def scan_folder_header(folder_name: str):
    print(f"\n[{folder_name}]")
    print("-" * 40)

def scan_progress(folders: int, files: int, shortcuts: int = 0):
    from ..primitives import print_progress
    shortcut_info = f", {shortcuts} shortcuts" if shortcuts else ""
    print_progress(f"Scanning... {folders} folders, {files} files{shortcut_info}")

def scanning_folder():
    print(f"  {_c.DIM}Scanning folder...{_c.RESET}")


# === Folder status messages ===

def folder_status_empty(filtered_count: int = 0):
    parts = ["no files"]
    if filtered_count > 0:
        parts.append(f"{_c.DIM}{filtered_count} filtered{_c.RESET}")
    print(f"  {', '.join(parts)}")

def folder_status_synced(file_count: int, filtered_count: int = 0):
    parts = [f"{file_count} files"]
    if filtered_count > 0:
        parts.append(f"{_c.DIM}{filtered_count} filtered{_c.RESET}")
    print(f"  {', '.join(parts)} • {_c.GREEN}✓ synced{_c.RESET}")

def folder_status_downloading(to_download: int, total_size: int, skipped: int = 0, filtered_count: int = 0):
    parts = [f"{to_download} files ({format_size(total_size)})"]
    if skipped > 0:
        parts.append(f"{skipped} synced")
    if filtered_count > 0:
        parts.append(f"{_c.DIM}{filtered_count} filtered{_c.RESET}")
    print(f"  {', '.join(parts)}")


# === Download messages ===

def download_starting(file_count: int, chart_count: int, max_workers: int):
    print(f"  Downloading {file_count} files across {chart_count} charts...")
    print(f"  (max {max_workers} concurrent downloads, press ESC to cancel)")
    print()

def download_cancelled(downloaded: int, complete_charts: int, cleaned: int = 0):
    print(f"  Cancelled. Downloaded {downloaded} files ({complete_charts} complete charts).")
    if cleaned > 0:
        print(f"  Cleaned up {cleaned} partial download(s).")


# === Folder completion summary ===

def folder_complete(downloaded: int, bytes_downloaded: int, duration: float, errors: int = 0):
    avg_speed = bytes_downloaded / duration if duration > 0 else 0
    summary = f"  {_c.GREEN}✓{_c.RESET} {downloaded} files"
    if bytes_downloaded > 0:
        summary += f" ({format_size(bytes_downloaded)})"
    summary += f" in {format_duration(duration)}"
    if avg_speed > 0:
        summary += f" • {format_speed(avg_speed)}"
    if errors > 0:
        summary += f" • {_c.RED}{errors} errors{_c.RESET}"
    print(summary)


# === Multi-folder completion summary ===

def sync_cancelled(downloaded: int = 0):
    summary = f"{_c.DIM}Cancelled{_c.RESET}"
    if downloaded > 0:
        summary += f" - {downloaded} files downloaded"
    print(summary)

def sync_complete(downloaded: int, bytes_downloaded: int, duration: float):
    avg_speed = bytes_downloaded / duration if duration > 0 else 0
    summary = f"{_c.GREEN}✓{_c.RESET} {downloaded} files"
    if bytes_downloaded > 0:
        summary += f" ({format_size(bytes_downloaded)})"
    summary += f" in {format_duration(duration)}"
    if avg_speed > 0:
        summary += f" • {format_speed(avg_speed)} avg"
    print(summary)

def sync_already_synced():
    print(f"{_c.GREEN}✓{_c.RESET} All files synced")

def sync_errors(error_count: int):
    print(f"  {_c.RED}{error_count} errors{_c.RESET}")

def sync_rate_limited(count: int):
    print(f"  {_c.DIM}{count} rate-limited{_c.RESET}")

def rate_limit_guidance(folder_names: set[str]):
    print()
    folder_list = ", ".join(sorted(folder_names))
    print(f"  {_c.DIM}[{folder_list}] hit Google's download limit.{_c.RESET}")
    print(f"  {_c.DIM}Run sync again later, or try tomorrow (resets every 24h).{_c.RESET}")


# === Purge messages ===

def purge_drive_disabled(folder_name: str, file_count: int, total_size: int):
    print(f"\n{_c.DIM}[{folder_name}]{_c.RESET} (drive disabled)")
    print(f"  Found {_c.RED}{file_count}{_c.RESET} files ({format_size(total_size)})")

def purge_folder(folder_name: str, file_count: int, total_size: int):
    print(f"\n{_c.DIM}[{folder_name}]{_c.RESET}")
    print(f"  Found {_c.RED}{file_count}{_c.RESET} files to purge ({format_size(total_size)})")

def purge_tree_lines(lines: list[str], max_lines: int = 5):
    for line in lines[:max_lines]:
        print(f"  {line}")
    if len(lines) > max_lines:
        print(f"    ... and {len(lines) - max_lines} more folders")

def purge_removed(deleted: int, failed: int = 0):
    msg = f"  {_c.RED}Removed {deleted} files{_c.RESET}"
    if failed > 0:
        msg += f" ({failed} failed)"
    print(msg)

def purge_partial_downloads(file_count: int, total_size: int):
    print(f"\n{_c.DIM}[Partial Downloads]{_c.RESET}")
    print(f"  Found {_c.RED}{file_count}{_c.RESET} incomplete download(s) ({format_size(total_size)})")

def purge_partial_cleaned(deleted: int, failed: int = 0):
    msg = f"  {_c.RED}Cleaned up {deleted} file(s){_c.RESET}"
    if failed > 0:
        msg += f" ({failed} failed)"
    print(msg)

def purge_summary(deleted: int, total_size: int, failed: int = 0):
    print(f"{_c.RED}✗{_c.RESET} Removed {deleted} files ({format_size(total_size)})")
    if failed > 0:
        print(f"  {_c.DIM}{failed} file(s) could not be deleted{_c.RESET}")

def purge_nothing():
    print(f"{_c.GREEN}✓{_c.RESET} No files to purge")


# === Download errors ===

def download_errors_header():
    print()
    print(f"{_c.RED}Download errors:{_c.RESET}")

def download_errors_context(context: str, errors: list, show_all: bool = False, sample_size: int = 3):
    if show_all or len(errors) <= sample_size:
        print(f"  {_c.DIM}[{context}]{_c.RESET} {len(errors)} failed:")
        for err in errors:
            print(f"    - {err.filename} ({err.reason})")
    elif len(errors) <= 100:
        print(f"  {_c.DIM}[{context}]{_c.RESET} {len(errors)} failed:")
        for err in errors[:sample_size]:
            print(f"    - {err.filename} ({err.reason})")
        print(f"    ... and {len(errors) - sample_size} more")
    else:
        print(f"  {_c.DIM}[{context}]{_c.RESET} {len(errors)} failed")
