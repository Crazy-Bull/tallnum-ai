@echo off
cd /d "%~dp0"
if not exist "out\main\index.js" (
  echo Please run npm run build first.
  pause
  exit /b 1
)
if not exist "node_modules\electron\dist\electron.exe" (
  echo Please install desktop dependencies first.
  pause
  exit /b 1
)
start "" "node_modules\electron\dist\electron.exe" "."
