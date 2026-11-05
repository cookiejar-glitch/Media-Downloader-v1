@echo off
title Media Converter
cd /d "%~dp0"
set NEEDRESTART=0

if not exist "MediaConverter.pyw" (
  echo Could not find MediaConverter.pyw in this folder:
  echo %~dp0
  echo Put MediaConverter.pyw in the SAME folder as this file, then run this again.
  pause
  exit /b
)

echo Updating components (the YouTube tab needs these)...
py -m pip install --upgrade yt-dlp yt-dlp-ejs PySide6 imageio-ffmpeg

where deno >nul 2>nul || (echo Installing Deno, which YouTube needs... & winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements & set NEEDRESTART=1)

if "%NEEDRESTART%"=="1" (
  echo.
  echo Deno was installed. Please CLOSE this window and double-click this file again.
  pause
  exit /b
)

echo Starting Media Converter...
start "" pyw "MediaConverter.pyw"
