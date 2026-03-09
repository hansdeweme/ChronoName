# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).

import argparse, json, os, re, subprocess, sys, time, hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
# ---------------------------------------------------------------------------------------------------------
# Note:  "TimeZone=Asia/Bangkok" is needed to get correct local times for QuickTime videos recorded in that timezone, 
#        otherwise exiftool gives back UTC time which may mess up the ordering and cause name clashes. 
#        Adjust as needed for the timezone or remove to get UTC-based names. 
# ------------------------------------
# to revert: python rename_datetime.py --undo rename_log_XXXXXXXX.json

# Solve "access denied"  problems in Windows when renaming files in place:
# - Make sure inheritance is on at the root of the library:
#       icacls "H:\Galleries" /inheritance:e
# - Give yourself user-rights that propagate to all files/subfolders:
#       icacls "H:\Galleries" /grant "HDWDESK\Hans:(OI)(CI)M"
# - Use F instead of M if you prefer Full control. The (OI)(CI) makes it propagate to all new files/folders created under it
# - Push this down the existing tree (add /t to recurse, /c to continue on errors)
#       icacls "H:\Galleries" /grant "HDWDESK\Hans:(OI)(CI)M" /t /c

SUPPORTED_EXT = {"jpg","jpeg","heic","png","dng","cr2","cr3","arw","nef","raf","mp4","mov","m4v"}
VIDEO_KEYS = {"CreateDate", "MediaCreateDate", "TrackCreateDate"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}

def _to_name_tz(dt: datetime, source: str, ext: str, name_tz: ZoneInfo) -> datetime:
    """
    Deterministic timezone policy:
    - For videos: treat QuickTime date tags as UTC unless they already carry tzinfo, then convert to name_tz.
    - For stills: keep as-is (camera local time) unless tzinfo is present, then convert.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(name_tz).replace(tzinfo=None)

    is_video = ext.lower() in VIDEO_EXTS and source in VIDEO_KEYS
    if is_video:
        # QuickTime tags: interpret naive as UTC and convert to desired naming timezone
        dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt_utc.astimezone(name_tz).replace(tzinfo=None)

    # still image without tzinfo: assume it's already local capture time (don’t shift)
    return dt


def _exiftool_bin() -> str:
    local = Path(__file__).with_name("exiftool.exe")
    if local.exists():
        return str(local)
    local2 = Path(__file__).with_name("exiftool")
    if local2.exists():
        return str(local2)
    return "exiftool"

def _fmt_secs(s: float) -> str:
    s = int(max(0, s))
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:d}:{sec:02d}"

def _progress_line(done: int, total: int, start_ts: float) -> str:
    elapsed = time.time() - start_ts
    rate = (done / elapsed) if elapsed > 0 else 0.0
    pct = (done / total * 100.0) if total else 100.0
    eta = ((total - done) / rate) if rate > 0 and total else 0.0
    return f"{done}/{total} ({pct:5.1f}%) | {rate:6.1f}/s | ETA {_fmt_secs(eta)} | elapsed {_fmt_secs(elapsed)}"

def _exiftool_bin() -> str:
    local = Path(__file__).with_name("exiftool.exe")
    if local.exists():
        return str(local)
    local2 = Path(__file__).with_name("exiftool")
    if local2.exists():
        return str(local2)
    return "exiftool"


def call_exiftool_json_with_spinner(root: Path) -> list[dict]:
    out_path = Path.cwd() / "__exiftool_scan.json"

    cmd = [
        _exiftool_bin(),
        "-r",
        "-json",
        "-api", "QuickTimeUTC=1",
        "-api", "TimeZone=Asia/Bangkok",
        "-api", "largefilesupport=1",
        "-charset", "filename=utf8",
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

    # stream stdout to file (like: exiftool ... > out.json)
    with open(out_path, "w", encoding="utf-8") as f_out:
        p = subprocess.Popen(
            cmd,
            stdout=f_out,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        spinner = "|/-\\"
        i = 0
        t0 = time.time()

        while True:
            rc = p.poll()
            if rc is not None:
                break
            print(
                f"\r[exiftool] scanning metadata... {spinner[i % len(spinner)]}  elapsed {_fmt_secs(time.time() - t0)}",
                end="",
                flush=True,
            )
            i += 1
            time.sleep(0.15)

        print("\r" + " " * 90 + "\r", end="")  # clear spinner

        err = (p.stderr.read() if p.stderr else "")
        if p.returncode != 0:
            if err.strip():
                print(err.strip(), file=sys.stderr)
            raise RuntimeError("exiftool failed")

    try:
        with open(out_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return []
        return json.loads(raw)
    finally:
        try:
            out_path.unlink()
        except OSError:
            pass

def have_exiftool() -> bool:
    try:
        subprocess.run(["exiftool", "-ver"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        return False

def call_exiftool_json(root: Path) -> list[dict]:
    # Ask only for what we need; JSON is easiest to parse robustly.
    cmd = [
        _exiftool_bin(),
        "-r",
        "-api", "QuickTimeUTC=1",
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
    # Limit by extensions for speed and to avoid renaming non-media by accident
    for ext in sorted(SUPPORTED_EXT):
        cmd += ["-ext", ext]
    cmd += [str(root)]

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(p.stderr.strip(), file=sys.stderr)
        raise RuntimeError("exiftool failed")
    return json.loads(p.stdout)

def parse_exif_dt(s: str | None) -> datetime | None:
    """
    exiftool emits like '2021:07:04 15:23:12', maybe with '.123' or '+02:00'.
    We normalize to ISO and let fromisoformat parse.
    """
    if not s:
        return None
    s = s.strip()
    # Replace first two ':' in the date part with '-' to get YYYY-MM-DD
    # Preserve timezone if present.
    m = re.match(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)(.*)$", s)
    if not m:
        return None
    y, mo, d, H, M, S, tail = m.groups()
    iso = f"{y}-{mo}-{d} {H}:{M}:{S}{tail}"
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None

def sanitize(s: str) -> str:
    s = s.strip().upper().replace("  ", " ")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^A-Z0-9\-]+", "", s)
    return s[:24]

def choose_best_dt(meta: dict) -> tuple[datetime | None, str]:
    # Preference order for stills/videos; you can tweak
    for key in ("SubSecDateTimeOriginal","DateTimeOriginal","CreateDate","MediaCreateDate","TrackCreateDate","FileModifyDate"):
        dt = parse_exif_dt(meta.get(key))
        if dt:
            return dt, key
    return None, "None"

def already_good_name(name: str) -> bool:
    # Detect names already starting with YYYYMMDD_HHMMSS
    return bool(re.match(r"^\d{8}_\d{6}", name, re.IGNORECASE))

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def build_manifest_entry(
    *,
    old_path: Path,
    new_path: Path,
    old_name: str,
    dt: datetime,
    source: str,
    meta: dict,
    include_device: bool,
    include_hash: bool,
) -> dict:
    entry = {
        "file": str(new_path),
        "filename": new_path.name,
        "directory": str(new_path.parent),
        "timestamp": dt.isoformat(),
        "timestamp_source": source,
        "original_path": str(old_path),
        "original_filename": old_name,
        "extension": new_path.suffix.lower(),
    }
    if include_device:
        make = str(meta.get("Make") or "").strip()
        model = str(meta.get("Model") or "").strip()
        if make:
            entry["make"] = make
        if model:
            entry["model"] = model
    if include_hash and new_path.exists():
        entry["sha256"] = sha256_file(new_path)
    return entry

def main():
    ap = argparse.ArgumentParser(description="Batch rename photos/videos in a year folder by capture time.")
    ap.add_argument("root", type=Path, help="Top-level year folder, e.g. D:\\Photos\\2021")
    ap.add_argument("--name-tz", default="Asia/Bangkok", help="Timezone used for output filenames (IANA tz, e.g. Asia/Bangkok, or Europe/Amsterdam for UTC+1).")    
    ap.add_argument("--dry-run", action="store_true", help="Show what would change, do not rename")
    ap.add_argument("--include-device", action="store_true", help="Append __MAKE-MODEL to filename")
    ap.add_argument("--skip-already", action="store_true", help="Skip files that already look timestamped")
    ap.add_argument("--log", type=Path, default=None, help="Path for rename log JSON (default auto)")
    ap.add_argument("--undo", type=Path, default=None, help="Undo a previous run using its JSON log")
    ap.add_argument("--progress-every", type=int, default=100, help="Progress update interval (items). 0 disables.")    
    ap.add_argument("--no-progress", action="store_true", help="Disable progress output")    
    ap.add_argument("--manifest", type=Path, default=None, help="Write a collection manifest JSON (default auto when enabled).")
    ap.add_argument("--write-manifest", action="store_true", help="Write a collection manifest describing the normalized archive state.")
    ap.add_argument("--manifest-hash", action="store_true", help="Include SHA-256 hashes in the collection manifest (slower).")        
    args = ap.parse_args()

    if args.undo:
        with open(args.undo, "r", encoding="utf-8") as f:
            ops = json.load(f)
        # Reverse in descending path length to avoid clashes
        for entry in sorted(ops, key=lambda e: len(e["new"]), reverse=True):
            src = Path(entry["new"])
            dst = Path(entry["old"])
            if src.exists():
                print(f"UNDO: {src} -> {dst}")
                if not args.dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(src, dst)
            else:
                print(f"SKIP: missing {src}")
        print("Undo complete.")
        return

    root = args.root
    if not root.exists():
        print(f"Not found: {root}", file=sys.stderr)
        sys.exit(1)

    if not have_exiftool():
        print("exiftool not found on PATH. Install it first (brew/choco/apt).", file=sys.stderr)
        sys.exit(1)

    data = call_exiftool_json_with_spinner(root) if not args.no_progress else call_exiftool_json(root)
    ops = []
    per_dir_counters: dict[Path, dict[str,int]] = {}
    manifest_entries = []

    t_ops = time.time()
    total = len(data)
    progress_every = 0 if args.no_progress else max(0, int(args.progress_every))
    for i, meta in enumerate(data, start=1):
        old_path = Path(meta.get("SourceFile") or (Path(meta["Directory"]) / meta["FileName"]))
        directory = old_path.parent
        old_name = old_path.name
        ext = old_path.suffix

        # Safety: only process certain extensions, and files that actually exist
        if old_path.suffix.lower().lstrip(".") not in SUPPORTED_EXT:
            continue
        if not old_path.exists():
            continue
        if args.skip_already and already_good_name(old_name):
            continue

        dt, source = choose_best_dt(meta)
        name_tz = ZoneInfo(args.name_tz)
        dt = _to_name_tz(dt, source, ext, name_tz)        
        if not dt:
            # Nothing usable; skip
            continue

        # Base time; include milliseconds if available
        base = dt.strftime("%Y%m%d_%H%M%S")
        # Try to capture subsecond if present
        subsec_raw = meta.get("SubSecDateTimeOriginal")
        if subsec_raw and "." in subsec_raw:
            ms = subsec_raw.split(".")[-1]
            ms = re.sub(r"\D", "", ms)[:3].ljust(3, "0")
            base = f"{base}_{ms}"

        device = ""
        if args.include_device:
            make = sanitize(str(meta.get("Make") or ""))
            model = sanitize(str(meta.get("Model") or ""))
            if model and make and model.startswith(make):
                device = f"__{model}"
            elif make or model:
                device = "__" + "-".join([x for x in (make, model) if x])

        # Build a unique name within the directory
        per_dir_counters.setdefault(directory, {})
        counter_key = base + device
        cnt = per_dir_counters[directory].get(counter_key, 0)

        while True:
            suffix = f"_{cnt:03d}" if cnt > 0 else ""
            new_name = f"{base}{device}{suffix}{ext}"
            new_path = directory / new_name
            if not new_path.exists():
                break
            cnt += 1

        per_dir_counters[directory][counter_key] = cnt
        if old_path == new_path:
            continue

        ops.append({
            "old": str(old_path),
            "new": str(new_path),
            "source": source
        })
        if args.write_manifest:
            manifest_entries.append({
                "old_path": old_path,
                "new_path": new_path,
                "old_name": old_name,
                "dt": dt,
                "source": source,
                "meta": meta,
            })        
                       
        
        if progress_every and (i % progress_every == 0 or i == total):
            print("\r[plan] " + _progress_line(i, total, t_ops), end="", flush=True)                       
        
    if progress_every:
        print()

    if not data:
        print("No supported media files found.")
        return

    if not ops:
        print("Nothing to rename.")
        return

    # Choose log path
    log_path = args.log or Path.cwd() / f"rename_log_{int(time.time())}.json"
    print(f"Planned renames: {len(ops)}")
    for e in ops[:20]:
        print(f"{Path(e['old']).name}  ->  {Path(e['new']).name}  ({e['source']})")
    if len(ops) > 20:
        print(f"... and {len(ops)-20} more")

    if args.dry_run:
        print(f"[dry-run] No changes written. Log not saved.")
        if args.write_manifest:
            print("[dry-run] Manifest not written because files were not renamed.")
        return
    
    # Execute
    t_ren = time.time()
    n_ops = len(ops)
    for j, e in enumerate(ops, start=1):
        src = Path(e["old"])
        dst = Path(e["new"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        if progress_every and (j % progress_every == 0 or j == n_ops):
            print("\r[rename] " + _progress_line(j, n_ops, t_ren), end="", flush=True)        

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(ops, f, ensure_ascii=False, indent=2)

    print(f"Done. Renamed {len(ops)} files.")
    print(f"Undo log saved to: {log_path}")

    if args.write_manifest:
        manifest_path = args.manifest or Path.cwd() / f"collection_manifest_{int(time.time())}.json"

        manifest = []
        for item in manifest_entries:
            manifest.append(
                build_manifest_entry(
                    old_path=item["old_path"],
                    new_path=item["new_path"],
                    old_name=item["old_name"],
                    dt=item["dt"],
                    source=item["source"],
                    meta=item["meta"],
                    include_device=args.include_device,
                    include_hash=args.manifest_hash,
                )
            )

        manifest_doc = {
            "created_at": datetime.now().isoformat(),
            "root": str(root),
            "name_timezone": args.name_tz,
            "include_device": args.include_device,
            "include_hash": args.manifest_hash,
            "entry_count": len(manifest),
            "entries": manifest,
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_doc, f, ensure_ascii=False, indent=2)

        print(f"Collection manifest saved to: {manifest_path}")

if __name__ == "__main__":
    main()
