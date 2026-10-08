"""Build ChronoName and preserve ExifTool's external portable runtime layout."""
import argparse
import shutil
import sys
from pathlib import Path

from PyInstaller.__main__ import run


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--distpath", default=str(root / "dist"))
    options, _ = parser.parse_known_args()
    run([
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--contents-directory", ".", "--name", "ChronoName",
        "--icon", str(root / "icon.png"), "--specpath", str(root / "build"),
        "--collect-submodules", "hdw_dedup_engine",
        "--collect-all", "pillow_heif", "--collect-all", "send2trash",
        "--exclude-module", "skimage", "--exclude-module", "scipy",
        "--add-data", f"{root / 'settings.json'};.",
        "--add-data", f"{root / 'icon.png'};.",
        *sys.argv[1:], str(root / "main.py"),
    ])
    destination = Path(options.distpath).resolve() / "ChronoName"
    # PyInstaller's binary dependency collection relocates perl532.dll beside
    # the launcher, which breaks Perl's relative @INC. Copy the untouched
    # external tool after collection instead of analyzing its binaries.
    shutil.copy2(root / "exiftool.exe", destination / "exiftool.exe")
    shutil.copytree(root / "exiftool_files", destination / "exiftool_files", dirs_exist_ok=True)
    print(f"ChronoName build complete: {destination / 'ChronoName.exe'}")


if __name__ == "__main__":
    main()
