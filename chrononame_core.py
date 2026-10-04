# chrononame_core.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# core planning, renaming, manifest, undo, timestamp logic
# - rule engine -
#

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from exiftool_adapter import (
    SUPPORTED_EXT,
    call_exiftool_json,
    call_exiftool_json_with_spinner,
    have_exiftool,
)
from models import (
    ChronoNameFilename,
    ManifestPlanEntry,
    ProgressCallback,
    RenameOperation,
    RenameOptions,
    RenamePlan,
    RenameResult,
    TimestampDecision,
    UndoResult,
)


VIDEO_KEYS = {"CreateDate", "MediaCreateDate", "TrackCreateDate"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
CAPTURE_KEYS = ("SubSecDateTimeOriginal", "DateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate")
CHRONONAME_FILENAME_RE = re.compile(
    r"^(?P<date>\d{8})_(?P<time>\d{6})"
    r"(?:_(?P<milliseconds>\d{3}))?"
    r"(?:__(?P<device>.*?))?"
    r"(?:_(?P<collision_counter>\d{3}))?$",
    re.IGNORECASE,
)


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
        dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt_utc.astimezone(name_tz).replace(tzinfo=None)

    return dt


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


def next_free_name(dst: Path) -> Path:
    if not dst.exists():
        return dst

    stem = dst.stem
    suffix = dst.suffix
    parent = dst.parent

    m = re.match(r"^(.*)_(\d{3})$", stem)
    if m:
        base = m.group(1)
        n = int(m.group(2))
    else:
        base = stem
        n = 1

    while True:
        n += 1
        candidate = parent / f"{base}_{n:03d}{suffix}"
        if not candidate.exists():
            return candidate


def parse_exif_dt(s: object | None) -> datetime | None:
    """
    exiftool emits like '2021:07:04 15:23:12', maybe with '.123' or '+02:00'.
    We normalize to ISO and let fromisoformat parse.
    """
    if isinstance(s, datetime):
        return s
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)(.*)$", s)
    if not m:
        return None
    y, mo, d, H, M, S, tail = m.groups()
    iso = f"{y}-{mo}-{d} {H}:{M}:{S}{tail}"
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def parse_filename_datetime(filename: str) -> datetime | None:
    chrononame = parse_chrononame_filename(filename)
    if chrononame:
        return chrononame.datetime

    patterns = [
        r"^(?:IMG|VID)-(\d{8})-WA\d+",
        r"^PXL_(\d{8})_(\d{6})",
        r"^Screenshot_(\d{8})[-_](\d{6})",
        r"^(\d{8})_(\d{6})",
    ]
    for pattern in patterns:
        match = re.match(pattern, filename, re.IGNORECASE)
        if not match:
            continue
        try:
            if len(match.groups()) == 1:
                return datetime.strptime(match.group(1), "%Y%m%d")
            return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None


def parse_chrononame_filename(filename: str | Path) -> ChronoNameFilename | None:
    path = Path(filename)
    stem = path.stem
    match = CHRONONAME_FILENAME_RE.match(stem)
    if not match:
        return None
    try:
        parsed_datetime = datetime.strptime(
            match.group("date") + match.group("time"),
            "%Y%m%d%H%M%S",
        )
    except ValueError:
        return None

    milliseconds = match.group("milliseconds")
    collision_counter = match.group("collision_counter")
    return ChronoNameFilename(
        datetime=parsed_datetime,
        milliseconds=int(milliseconds) if milliseconds is not None else None,
        device=match.group("device") or "",
        collision_counter=int(collision_counter) if collision_counter is not None else None,
        extension=path.suffix.lower(),
    )


def first_capture_datetime(meta: dict) -> tuple[datetime | None, str, list[str]]:
    rejected_candidates = []
    for key in CAPTURE_KEYS:
        raw_value = meta.get(key)
        dt = parse_exif_dt(raw_value)
        if dt:
            return dt, key, rejected_candidates
        if raw_value:
            rejected_candidates.append(key)
    return None, "None", rejected_candidates


def sanitize(s: str) -> str:
    s = s.strip().upper().replace("  ", " ")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^A-Z0-9\-]+", "", s)
    return s[:24]


def evaluate_timestamp_decision(
    meta: dict,
    *,
    path: Path | None = None,
    name_tz: ZoneInfo,
    include_filename: bool = True,
    include_file_modify: bool = True,
    already_named: bool = False,
) -> TimestampDecision:
    path = path or Path(meta.get("SourceFile") or (Path(meta["Directory"]) / meta["FileName"]))
    extension = path.suffix.lower()
    filename = path.name
    warnings: list[str] = []

    capture_datetime, capture_source, rejected_candidates = first_capture_datetime(meta)
    filename_datetime = parse_filename_datetime(filename) if include_filename else None
    file_modify_datetime = parse_exif_dt(meta.get("FileModifyDate")) if include_file_modify else None

    chosen_datetime = None
    source = "none"
    confidence = "unknown"

    if capture_datetime:
        chosen_datetime = _to_name_tz(capture_datetime, capture_source, extension, name_tz)
        source = capture_source
        if extension in VIDEO_EXTS and capture_source in VIDEO_KEYS:
            confidence = "high_video_metadata"
        else:
            confidence = "high_embedded_metadata"
    elif filename_datetime:
        chosen_datetime = filename_datetime
        source = "filename_datetime"
        confidence = "medium_filename"
        if file_modify_datetime and file_modify_datetime.date() == filename_datetime.date():
            chosen_datetime = filename_datetime.replace(
                hour=file_modify_datetime.hour,
                minute=file_modify_datetime.minute,
                second=file_modify_datetime.second,
            )
            source = "filename_date+filemodify_time_same_day"
            confidence = "medium_tentative_time"
    elif file_modify_datetime:
        chosen_datetime = _to_name_tz(file_modify_datetime, "FileModifyDate", extension, name_tz)
        source = "FileModifyDate"
        confidence = "low_file_modify_only"
        warnings.append("metadata_missing_capture_time")
    else:
        warnings.append("missing_usable_timestamp")

    if capture_datetime and filename_datetime and capture_datetime.date() != filename_datetime.date():
        warnings.append("metadata_filename_date_conflict")
    if file_modify_datetime and filename_datetime:
        delta_days = abs((file_modify_datetime.date() - filename_datetime.date()).days)
        if delta_days > 1:
            warnings.append("file_modify_filename_date_conflict")
    if chosen_datetime:
        sanity_datetime = chosen_datetime
        if sanity_datetime.tzinfo is not None:
            sanity_datetime = sanity_datetime.astimezone(name_tz).replace(tzinfo=None)
        if sanity_datetime.year < 1990:
            warnings.append("very_old_timestamp")
        if sanity_datetime > datetime.now().replace(tzinfo=None):
            warnings.append("future_timestamp")
        if sanity_datetime.hour == 0 and sanity_datetime.minute == 0 and sanity_datetime.second == 0:
            warnings.append("date_only_midnight")
    if already_named:
        warnings.append("already_chrononamed")

    return TimestampDecision(
        chosen_datetime=chosen_datetime,
        source=source,
        confidence=confidence,
        warnings=warnings,
        rejected_candidates=rejected_candidates,
    )


def choose_best_dt(meta: dict, *, path: Path | None = None, name_tz: ZoneInfo | None = None) -> tuple[datetime | None, str]:
    decision = evaluate_timestamp_decision(
        meta,
        path=path,
        name_tz=name_tz or ZoneInfo("Europe/Amsterdam"),
        include_filename=False,
        include_file_modify=True,
    )
    return decision.chosen_datetime, decision.source


def already_good_name(name: str) -> bool:
    return parse_chrononame_filename(name) is not None


def _raise_if_cancelled(cancel_callback=None) -> None:
    if cancel_callback and cancel_callback():
        raise RuntimeError("Operation cancelled.")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024, cancel_callback=None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            _raise_if_cancelled(cancel_callback)
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
    cancel_callback=None,
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
        entry["sha256"] = sha256_file(new_path, cancel_callback=cancel_callback)
    return entry


def _emit_progress(
    callback: ProgressCallback | None,
    stage: str,
    done: int,
    total: int,
    message: str,
) -> None:
    if callback:
        callback(stage, done, total, message)


def _undo_journal_path(log_path: Path) -> Path:
    if log_path.suffix:
        return log_path.with_suffix(".jsonl")
    return log_path.with_name(f"{log_path.name}.jsonl")


def _append_undo_journal_entry(journal_file, operation: RenameOperation) -> None:
    journal_file.write(json.dumps(operation.to_log_entry(), ensure_ascii=False) + "\n")
    journal_file.flush()
    os.fsync(journal_file.fileno())


def _load_undo_entries(log_path: Path) -> list[dict]:
    if log_path.suffix.lower() == ".jsonl":
        entries = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        break
        return entries

    with open(log_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _source_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _source_matches_plan(operation: RenameOperation) -> bool:
    if operation.source_size is None or operation.source_mtime_ns is None:
        return True
    try:
        source_size, source_mtime_ns = _source_signature(operation.old_path)
    except FileNotFoundError:
        return False
    return (
        source_size == operation.source_size
        and source_mtime_ns == operation.source_mtime_ns
    )


def scan_metadata(options: RenameOptions) -> list[dict]:
    root = options.root
    if not root.exists():
        raise FileNotFoundError(f"Not found: {root}")

    if not have_exiftool():
        raise RuntimeError("exiftool not found on PATH. Install it first (brew/choco/apt).")

    if options.show_progress:
        return call_exiftool_json_with_spinner(
            root,
            exiftool_timezone=options.name_tz,
            progress_callback=options.progress_callback,
            cancel_callback=options.cancel_callback,
        )

    return call_exiftool_json(
        root,
        exiftool_timezone=options.name_tz,
        cancel_callback=options.cancel_callback,
    )


def build_rename_plan(options: RenameOptions) -> RenamePlan:
    data = scan_metadata(options)
    ops: list[RenameOperation] = []
    per_dir_counters: dict[Path, dict[str, int]] = {}
    manifest_entries: list[ManifestPlanEntry] = []
    skipped_count = 0

    t_ops = time.time()
    total = len(data)
    progress_every = max(0, int(options.progress_every)) if options.show_progress else 0
    name_tz = ZoneInfo(options.name_tz)

    for i, meta in enumerate(data, start=1):
        _raise_if_cancelled(options.cancel_callback)
        old_path = Path(meta.get("SourceFile") or (Path(meta["Directory"]) / meta["FileName"]))
        directory = old_path.parent
        old_name = old_path.name
        ext = old_path.suffix

        if old_path.suffix.lower().lstrip(".") not in SUPPORTED_EXT:
            skipped_count += 1
            continue
        if not old_path.exists():
            skipped_count += 1
            continue
        if options.skip_already and already_good_name(old_name):
            skipped_count += 1
            continue

        decision = evaluate_timestamp_decision(
            meta,
            path=old_path,
            name_tz=name_tz,
            include_filename=False,
            include_file_modify=True,
        )
        dt = decision.chosen_datetime
        source = decision.source
        if not dt:
            skipped_count += 1
            continue

        base = dt.strftime("%Y%m%d_%H%M%S")

        subsec_raw = meta.get("SubSecDateTimeOriginal")
        if subsec_raw and "." in subsec_raw:
            ms = subsec_raw.split(".")[-1]
            ms = re.sub(r"\D", "", ms)[:3].ljust(3, "0")
            base = f"{base}_{ms}"

        device = ""
        if options.include_device:
            make = sanitize(str(meta.get("Make") or ""))
            model = sanitize(str(meta.get("Model") or ""))
            if model and make and model.startswith(make):
                device = f"__{model}"
            elif make or model:
                device = "__" + "-".join([x for x in (make, model) if x])

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
            skipped_count += 1
            continue

        source_size, source_mtime_ns = _source_signature(old_path)
        operation = RenameOperation(
            old_path=old_path,
            new_path=new_path,
            timestamp_source=source,
            source_size=source_size,
            source_mtime_ns=source_mtime_ns,
        )
        ops.append(operation)
        if options.write_manifest:
            manifest_entries.append(
                ManifestPlanEntry(
                    old_path=old_path,
                    new_path=new_path,
                    old_name=old_name,
                    dt=dt,
                    source=source,
                    meta=meta,
                )
            )

        if progress_every and (i % progress_every == 0 or i == total):
            message = _progress_line(i, total, t_ops)
            if options.progress_callback:
                _emit_progress(options.progress_callback, "plan", i, total, message)
            else:
                print("\r[plan] " + message, end="", flush=True)

    if progress_every and not options.progress_callback:
        print()

    return RenamePlan(
        root=options.root,
        operations=ops,
        manifest_entries=manifest_entries,
        metadata_count=total,
        skipped_count=skipped_count,
        name_tz=options.name_tz,
    )


def execute_rename_plan(plan: RenamePlan, options: RenameOptions) -> RenameResult:
    if options.dry_run or not plan.operations:
        return RenameResult(
            planned_count=len(plan.operations),
            renamed_count=0,
            skipped=[],
            operations=[],
        )

    log_path = options.log_path or Path.cwd() / f"rename_log_{int(time.time())}.json"
    journal_path = _undo_journal_path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    skipped = []
    renamed_count = 0
    executed_operations: list[RenameOperation] = []
    executed_manifest_entries: list[ManifestPlanEntry] = []
    t_ren = time.time()
    n_ops = len(plan.operations)
    progress_every = max(0, int(options.progress_every)) if options.show_progress else 0

    manifest_by_old = {entry.old_path: entry for entry in plan.manifest_entries}

    with open(journal_path, "a", encoding="utf-8") as journal_file:
        for j, operation in enumerate(plan.operations, start=1):
            _raise_if_cancelled(options.cancel_callback)
            src = operation.old_path
            dst = operation.new_path
            dst.parent.mkdir(parents=True, exist_ok=True)

            if not _source_matches_plan(operation):
                skipped.append(
                    "STALE PLAN: file changed after review\n"
                    f"file: {src}"
                )
                continue

            if dst.exists() and src != dst:
                skipped.append(
                    f"Conflict: planned destination is no longer available: {src} -> {dst}. "
                    "Build a new rename plan before processing again."
                )
                continue
            if src == dst:
                skipped.append(str(src))
                continue
            try:
                os.replace(src, dst)
            except PermissionError as exc:
                skipped.append(f"Permission denied: {src} -> {dst} ({exc})")
                continue
            except OSError as exc:
                skipped.append(f"Failed: {src} -> {dst} ({exc})")
                continue

            executed = RenameOperation(
                old_path=src,
                new_path=dst,
                timestamp_source=operation.timestamp_source,
                source_size=operation.source_size,
                source_mtime_ns=operation.source_mtime_ns,
            )
            executed_operations.append(executed)
            renamed_count += 1
            try:
                _append_undo_journal_entry(journal_file, executed)
            except OSError as exc:
                skipped.append(
                    f"Undo journal write failed after rename: {src} -> {dst} ({exc}). "
                    "Stopping before processing more files."
                )
                break

            manifest_entry = manifest_by_old.get(src)
            if manifest_entry:
                executed_manifest_entries.append(
                    ManifestPlanEntry(
                        old_path=manifest_entry.old_path,
                        new_path=dst,
                        old_name=manifest_entry.old_name,
                        dt=manifest_entry.dt,
                        source=manifest_entry.source,
                        meta=manifest_entry.meta,
                    )
                )

            if progress_every and (j % progress_every == 0 or j == n_ops):
                message = _progress_line(j, n_ops, t_ren)
                if options.progress_callback:
                    _emit_progress(options.progress_callback, "rename", j, n_ops, message)
                else:
                    print("\r[rename] " + message, end="", flush=True)

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(
            [operation.to_log_entry() for operation in executed_operations],
            f,
            ensure_ascii=False,
            indent=2,
        )

    manifest_path = None
    if options.write_manifest:
        manifest_path = options.manifest_path or Path.cwd() / f"collection_manifest_{int(time.time())}.json"
        manifest = []
        for item in executed_manifest_entries:
            _raise_if_cancelled(options.cancel_callback)
            manifest.append(
                build_manifest_entry(
                    old_path=item.old_path,
                    new_path=item.new_path,
                    old_name=item.old_name,
                    dt=item.dt,
                    source=item.source,
                    meta=item.meta,
                    include_device=options.include_device,
                    include_hash=options.manifest_hash,
                    cancel_callback=options.cancel_callback,
                )
            )

        manifest_doc = {
            "created_at": datetime.now().isoformat(),
            "root": str(plan.root),
            "name_timezone": plan.name_tz,
            "include_device": options.include_device,
            "include_hash": options.manifest_hash,
            "entry_count": len(manifest),
            "entries": manifest,
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_doc, f, ensure_ascii=False, indent=2)

    return RenameResult(
        planned_count=len(plan.operations),
        renamed_count=renamed_count,
        skipped=skipped,
        operations=executed_operations,
        log_path=log_path,
        journal_path=journal_path,
        manifest_path=manifest_path,
    )


def undo_renames(log_path: Path, dry_run: bool = False, cancel_callback=None) -> UndoResult:
    ops = _load_undo_entries(log_path)

    skipped = []
    undone_count = 0
    for entry in sorted(ops, key=lambda e: len(e["new"]), reverse=True):
        _raise_if_cancelled(cancel_callback)
        operation = RenameOperation.from_log_entry(entry)
        src = operation.new_path
        dst = operation.old_path
        if not src.exists():
            skipped.append(f"Missing: {src}")
            continue
        if dry_run:
            undone_count += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and src != dst:
            skipped.append(
                "UNDO CONFLICT:\n"
                f"wanted: {dst.name}\n"
                "reason: destination already exists"
            )
            continue
        if src == dst:
            skipped.append(str(src))
            continue
        try:
            os.replace(src, dst)
            undone_count += 1
        except PermissionError as exc:
            skipped.append(f"Permission denied: {src} -> {dst} ({exc})")

    return UndoResult(undone_count=undone_count, skipped=skipped)

