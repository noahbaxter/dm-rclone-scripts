# DM Chart Sync

Download Clone Hero charts from Google Drive. No setup required.

![Screenshot](screenshot.png)

## Usage

### Windows
Download `dm-sync.exe` from [Releases](../../releases) and run it.

### macOS
Download `dm-sync-macos` from [Releases](../../releases), then:
```bash
xattr -d com.apple.quarantine dm-sync-macos
chmod +x dm-sync-macos
./dm-sync-macos
```

### From Source
```bash
pip install -r requirements.txt
python sync.py
```

## Features

- **Smart sync** - only downloads new/changed files
- **Parallel downloads** with auto-retry on rate limits
- **Setlist filtering** - enable/disable individual setlists per drive
- **Custom folders** - add your own Google Drive folders
- **Optional sign-in** - get your own download quota for faster syncs
- **Archive support** - auto-extracts .7z/.zip/.rar archives with optional video removal
- **Purge** - clean up disabled content to free disk space

## RAR Support (Windows)

RAR files need **7-Zip** or **WinRAR** installed and added to PATH.

### Option 1: 7-Zip (recommended)
1. Install [7-Zip](https://www.7-zip.org/)
2. Add to PATH: `C:\Program Files\7-Zip`

### Option 2: WinRAR
1. Install [WinRAR](https://www.rarlab.com/download.htm)
2. Add to PATH: `C:\Program Files\WinRAR`

### How to add to PATH
1. Open Start Menu, search **"Environment Variables"**
2. Click **"Edit the system environment variables"**
3. Click **Environment Variables** button
4. Under **System variables**, select **Path** → **Edit**
5. Click **New** and paste the path from above
6. Click **OK** on all windows
7. **Restart DM Sync**

**Verify:** Open Command Prompt and type `7z` or `unrar` - you should see help text, not "not recognized".

## For Admins

### Manifest Updates

The manifest auto-updates daily via GitHub Actions.

**Manual trigger:** Actions → "Update Manifest" → Run workflow

**Setup:**
1. Create OAuth credentials at [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Run `python manifest_gen.py` locally to generate `token.json`
3. Add GitHub Secrets: `GOOGLE_CREDENTIALS`, `GOOGLE_TOKEN`, `GOOGLE_API_KEY`

### Building

Builds are automatic via GitHub Actions on push to main.

Manual build:
```bash
pip install pyinstaller
pyinstaller --onefile --name dm-sync sync.py
```
