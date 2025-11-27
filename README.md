# DM Chart Sync

**Zero-setup chart downloads for Drummer's Monthly members.**

No more rclone configuration, OAuth wizards, or Google Drive shortcuts. Just run the script and download.

## Quick Start (Users)

### Windows
1. Download `dm-sync.exe` from [Releases](../../releases)
2. Run it
3. Select which chart packs to download
4. Done!

### Python (Any OS)
```bash
pip install -r requirements.txt
python sync.py
```

## Features

- **Zero setup** - No OAuth, no API keys, no configuration
- **Smart sync** - Only downloads new/changed files
- **Parallel downloads** - Fast multi-threaded downloading
- **Custom folders** - Add your own public Google Drive folders
- **Cross-platform** - Windows, Mac, Linux

## How It Works

1. Chart folders are public ("Anyone with link")
2. A pre-built manifest contains the complete file tree
3. The app compares against your local files
4. Only missing/changed files are downloaded

This eliminates the need for every user to scan Google Drive (which would use thousands of API calls).

## For Admins

### Automatic Manifest Updates (GitHub Actions)

The manifest is automatically updated daily via GitHub Actions and stored as a release asset.

**To trigger manually:** Go to Actions → "Update Manifest" → Run workflow

**First-time setup:**
1. Create OAuth credentials at [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Run `python manifest_gen.py` locally once to generate `token.json`
3. Add GitHub Secrets:
   - `GOOGLE_CREDENTIALS`: Contents of `credentials.json`
   - `GOOGLE_TOKEN`: Contents of `token.json`

### Manual Updates

```bash
python manifest_gen.py          # Incremental (~1 API call)
python manifest_gen.py --full   # Full scan with resume
python manifest_gen.py --force  # Force complete rescan
```

### Building the Windows Executable

```bash
pip install pyinstaller
pyinstaller --onefile --name dm-sync --add-data "manifest.json:." sync.py
# Output: dist/dm-sync.exe
```

## Project Structure

```
dm-rclone-scripts/
├── sync.py              # User app - download charts
├── manifest_gen.py      # Admin - regenerate manifest
├── manifest.json        # Pre-built file tree (20MB)
├── requirements.txt     # Python dependencies
├── src/                 # Library code
│   ├── drive_client.py  # Google Drive API client
│   ├── manifest.py      # Manifest data structures
│   ├── config.py        # User configuration
│   ├── downloader.py    # Parallel file downloads
│   ├── scanner.py       # Folder scanning
│   ├── auth.py          # OAuth management
│   ├── changes.py       # Changes API tracking
│   └── utils.py         # Shared utilities
└── README.md
```

## Technical Details

- Uses Google Drive API v3 with API key (read-only, public folders only)
- Manifest approach reduces API calls from ~25,000/user to ~0/user
- Downloads via direct URL (`drive.google.com/uc?export=download`)
- Handles Google Drive shortcuts (links to other people's folders)
- Incremental manifest updates via Changes API (~1 API call vs ~16k)

## FAQ

**Why not use the old rclone approach?**
- Required 16+ step OAuth setup
- Users had to manually create Drive shortcuts
- Confusing for non-technical users

**Is my Google account required?**
- No! Since folders are public, no authentication needed.

**Can I add my own folders?**
- Yes! Press [C] in the app to add any public Google Drive folder.
