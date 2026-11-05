# Media Converter

A simple Windows app with drag-and-drop tabs:

- **Video → MP4** - turns any video into an MP4 that plays everywhere.
- **Audio** - turns audio (or the sound of a video) into OGG or MP3.
- **Merge** - combines files together.
- **YouTube** - paste a link and save the video as MP4 (or just the sound as MP3).

You see the final file size *before* converting. Themes, wallpaper and the save
folder are in **Settings**.

## Run it

1. Install [Python 3.9+](https://www.python.org/downloads/) (tick **Add Python to PATH**).
2. Double-click `MediaConverter.pyw`. The first time, it installs what it needs
   (needs internet once).

For YouTube links you also need [Deno](https://deno.com). The YouTube tab has an
**Install it now** button, or run `winget install DenoLand.Deno`. `Install_and_Run.bat`
does this for you.

## Make a single .exe

Put `MediaConverter.pyw`, `icon.ico` and `build_exe.bat` in one folder and double-click
`build_exe.bat`. You get `Media Converter.exe`, which needs no Python and no FFmpeg.

## Notes

- Only download videos you have the right to save.
- Built with [PySide6](https://doc.qt.io/qtforpython-6/), [FFmpeg](https://ffmpeg.org)
  (via `imageio-ffmpeg`) and [yt-dlp](https://github.com/yt-dlp/yt-dlp).
