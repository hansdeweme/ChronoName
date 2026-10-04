# exiftool_adapter.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# ExifTool subprocess integration
#

from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path
# local imports
from config import _resource_path
from models import CancelCallback, ProgressCallback
from report_paths import REPORTS_FOLDER_NAME

SUPPORTED_EXT = {"jpg","jpeg","heic","png","dng","cr2","cr3","arw","nef","raf","mp4","mov","m4v"}

def _exiftool_bin() -> str:
    local = _resource_path("exiftool.exe")
    if local.exists():
        return str(local)
    local2 = _resource_path("exiftool")
    if local2.exists():
        return str(local2)
    return "exiftool"


def _fmt_secs(s: float) -> str:
    s = int(max(0, s))
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:d}:{sec:02d}"


def _subprocess_no_window_kwargs() -> dict:
    if os.name == "nt":
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    return {}


def _exiftool_command(root: Path, exiftool_timezone: str) -> list[str]:
    cmd = [
        _exiftool_bin(),
        "-r",
        "-i", REPORTS_FOLDER_NAME,
        "-api", "QuickTimeUTC=1",
        "-api", f"TimeZone={exiftool_timezone}",
        "-api", "largefilesupport=1",
        "-charset", "filename=utf8",
        "-json",
        "-DateTimeOriginal",
        "-CreateDate",
        "-MediaCreateDate",
        "-TrackCreateDate",
        "-FileModifyDate",
        "-SubSecDateTimeOriginal",
        "-Make",
        "-Model",
        "-FileName",
        "-Directory",
        "-SourceFile",
    ]
    for ext in sorted(SUPPORTED_EXT):
        cmd += ["-ext", ext]
    cmd += [str(root)]
    return cmd


def have_exiftool() -> bool:
    try:
        subprocess.run(
            [_exiftool_bin(), "-ver"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            **_subprocess_no_window_kwargs(),
        )
        return True
    except Exception:
        return False


def call_exiftool_json_with_spinner(
    root: Path,
    exiftool_timezone: str = "Europe/Amsterdam",
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> list[dict]:
    out_path = Path.cwd() / "__exiftool_scan.json"
    cmd = _exiftool_command(root, exiftool_timezone)

    try:
        with open(out_path, "w", encoding="utf-8") as f_out:
            p = subprocess.Popen(
                cmd,
                stdout=f_out,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_subprocess_no_window_kwargs(),
            )

            spinner = "|/-\\"
            i = 0
            t0 = time.time()

            while True:
                if cancel_callback and cancel_callback():
                    p.terminate()
                    try:
                        p.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(timeout=2)
                    raise RuntimeError("Operation cancelled.")

                rc = p.poll()
                if rc is not None:
                    break
                message = f"elapsed {_fmt_secs(time.time() - t0)}"
                if progress_callback:
                    progress_callback("exiftool", 0, 0, message)
                else:
                    print(
                        f"\r[exiftool] scanning metadata... {spinner[i % len(spinner)]}  {message}",
                        end="",
                        flush=True,
                    )
                i += 1
                time.sleep(0.15)

            if not progress_callback:
                print("\r" + " " * 90 + "\r", end="")

            err = (p.stderr.read() if p.stderr else "").strip()
    except RuntimeError:
        try:
            out_path.unlink()
        except OSError:
            pass
        raise

    try:
        raw = out_path.read_text(encoding="utf-8").strip()
    finally:
        try:
            out_path.unlink()
        except OSError:
            pass

    return _parse_exiftool_json(raw, p.returncode, err)


def call_exiftool_json(
    root: Path,
    exiftool_timezone: str = "Europe/Amsterdam",
    cancel_callback: CancelCallback | None = None,
) -> list[dict]:
    p = subprocess.Popen(
        _exiftool_command(root, exiftool_timezone),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_subprocess_no_window_kwargs(),
    )
    while True:
        if cancel_callback and cancel_callback():
            p.terminate()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2)
            raise RuntimeError("Operation cancelled.")
        if p.poll() is not None:
            break
        time.sleep(0.05)

    stdout, stderr = p.communicate()
    return _parse_exiftool_json((stdout or "").strip(), p.returncode, (stderr or "").strip())


def _parse_exiftool_json(raw: str, returncode: int, stderr: str) -> list[dict]:
    if not raw and returncode == 0:
        return []

    if not raw:
        raise RuntimeError(
            f"exiftool produced no JSON output. Exit code={returncode}\n\n{stderr}"
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse exiftool JSON output. Exit code={returncode}\n\n{stderr}"
        ) from exc

    if returncode != 0:
        print(
            f"Warning: exiftool returned exit code {returncode}, "
            f"but JSON output was recovered successfully.",
            file=sys.stderr,
        )
        if stderr:
            print(stderr, file=sys.stderr)

    return data

