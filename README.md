# Synchotic

A Clone Hero chart downloader. Browse community chart packs, pick what you want, and sync.

![Screenshot](screenshot.png)

## Download

**[Download the latest release here](../../releases/latest)**

- **Windows:** Download `synchotic.exe` and run it
- **macOS:** Download `synchotic-macos`. macOS blocks apps from unknown developers, so open Terminal and run:
  ```
  cd ~/Downloads && chmod +x synchotic-macos && xattr -d com.apple.quarantine synchotic-macos
  ```
  Then double-click to run. (Move it somewhere else first if you don't want it in Downloads.)

## How It Works

1. Launch the app - it fetches the latest chart pack list automatically
2. Pick which chart packs you want (toggle with **Space**)
3. Press **S** to Sync - downloads enabled charts, removes disabled ones

Charts download to a `Sync Charts` folder next to the app.

## Controls

| Key | Action |
|-----|--------|
| **↑↓** or **1-9** | Navigate / jump to item |
| **Enter** | Open pack settings |
| **Space** | Toggle pack on/off |
| **S** | Sync all |
| **Tab** | Switch view (Size / Files / Charts) |
| **A** | Add custom Google Drive folder |
| **G** | Sign in/out of Google |
| **Esc** | Back / Quit |

## Features

- **Smart sync** - only downloads what's new or changed
- **Setlist filtering** - pick exactly which setlists you want from each drive
- **Custom folders** - add your own Google Drive folders
- **Sign in to Google** - optional, gives you faster downloads with your own quota
- **Auto-extract** - handles .zip, .7z, and .rar archives automatically

## Troubleshooting

### Downloads fail with path errors (Windows)

Windows blocks paths over 260 characters. To fix:

1. Open Registry Editor (`regedit`)
2. Go to `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem`
3. Set `LongPathsEnabled` to `1`
4. Restart your computer

### Where are my charts?

In the `Sync Charts` folder, next to where you ran the app.

### Where are logs?

`.dm-sync/logs/` next to the app. Each day gets its own log file.

---

## For Developers

<details>
<summary>Click to expand</summary>

### Running from Source

```bash
pip install -r requirements.txt
python sync.py
```

### Building

Builds are automatic via GitHub Actions on push to main.

```bash
pip install pyinstaller
pyinstaller --onefile --name synchotic sync.py
```

### Manifest Updates

The manifest auto-updates daily via GitHub Actions.

**Manual trigger:** Actions → "Update Manifest" → Run workflow

**Setup:**
1. Create OAuth credentials at [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Run `python manifest_gen.py` locally to generate `token.json`
3. Add GitHub Secrets: `GOOGLE_CREDENTIALS`, `GOOGLE_TOKEN`, `GOOGLE_API_KEY`

</details>
