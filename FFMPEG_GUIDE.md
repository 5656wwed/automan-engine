# FFmpeg Installation Guide (Windows)

AutoScene Studio requires FFmpeg for all video rendering operations.

## Option 1: Chocolatey (Recommended)

```bash
choco install ffmpeg
```

## Option 2: Scoop

```bash
scoop install ffmpeg
```

## Option 3: Manual Installation

1. Download FFmpeg from: https://ffmpeg.org/download.html
   - Choose "Windows builds from gyan.dev"
   - Download the **release full** build (.zip)

2. Extract to `C:\ffmpeg`

3. Add `C:\ffmpeg\bin` to your system PATH:
   - Open **System Properties** → **Advanced** → **Environment Variables**
   - Under **System variables**, find **Path** → **Edit**
   - Click **New** and add: `C:\ffmpeg\bin`
   - Click **OK** to save

4. Restart your terminal/Command Prompt.

## Verify Installation

```bash
ffmpeg -version
```

You should see version information. AutoScene Studio also has a built-in check:

```bash
python -m app.main check-ffmpeg
```

## Troubleshooting

- **"ffmpeg is not recognized"**: PATH not set correctly. Restart terminal after editing PATH.
- **Missing codecs**: Use the "full" build which includes libx264 and AAC.
- **Permission errors**: Run terminal as Administrator when installing via Chocolatey.
