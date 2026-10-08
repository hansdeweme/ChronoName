@echo off
setlocal

echo Building ChronoName...

py -3 -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --windowed ^
  --name ChronoName ^
  --collect-submodules hdw_dedup_engine ^
  --collect-all pillow_heif ^
  --collect-all send2trash ^
  --exclude-module skimage ^
  --exclude-module scipy ^
  main.py

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed.
    exit /b %errorlevel%
)

echo.
echo Copying ChronoName resources...

copy /Y ".\icon.png" ".\dist\ChronoName\icon.png"
copy /Y ".\settings.json" ".\dist\ChronoName\settings.json"
copy /Y ".\readme.md" ".\dist\ChronoName\readme.md"
copy /Y ".\exiftool.exe" ".\dist\ChronoName\exiftool.exe"

if exist ".\exiftool_files" (
    robocopy ".\exiftool_files" ".\dist\ChronoName\exiftool_files" /E

    REM Robocopy uses exit codes 0-7 for successful/non-fatal outcomes.
    if errorlevel 8 (
        echo.
        echo ERROR: Failed to copy exiftool_files.
        exit /b %errorlevel%
    )
)

echo.
echo ChronoName build complete.
echo Output: .\dist\ChronoName\ChronoName.exe

endlocal