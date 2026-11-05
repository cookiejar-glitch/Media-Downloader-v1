@echo off
REM ---------------------------------------------------------------------------
REM  Builds "Media Converter.exe" - one file you can give to anyone.
REM  It has everything inside (no Python or FFmpeg needed on their PC),
REM  the YouTube tab, and the play-button + music-note icon (icon.ico).
REM  Put this next to MediaConverter.pyw and icon.ico, then double-click it.
REM ---------------------------------------------------------------------------
cd /d "%~dp0"
echo Installing the build tools (one time)...
python -m pip install --upgrade --disable-pip-version-check pyinstaller PySide6 imageio-ffmpeg yt-dlp yt-dlp-ejs
if errorlevel 1 goto fail

for /f "delims=" %%i in ('python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"') do set FFEXE=%%i
set EXTRA=
for /f "delims=" %%d in ('where deno 2^>nul') do set EXTRA=--add-binary "%%d;."
if "%EXTRA%"=="" echo (Deno not found on this PC - the YouTube tab will offer to install it on first use.)
if not exist icon.ico python MediaConverter.pyw --write-icon icon.ico

echo Building... this takes a few minutes.
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "Media Converter" --icon icon.ico ^
  --add-binary "%FFEXE%;." %EXTRA% ^
  --collect-all yt_dlp --collect-all yt_dlp_ejs ^
  MediaConverter.pyw
if errorlevel 1 goto fail

copy /y "dist\Media Converter.exe" "%~dp0Media Converter.exe" >nul

echo.
echo Done!  Your program is:  Media Converter.exe   (right here, next to this file)
echo If you move it to your desktop and the icon looks plain for a moment, that is just
echo Windows catching up - it will show the play-button icon.
explorer /select,"%~dp0Media Converter.exe"
pause
exit /b 0

:fail
echo.
echo Something went wrong. Make sure Python is installed from python.org
echo (tick "Add Python to PATH" during setup) and try again.
pause
exit /b 1
