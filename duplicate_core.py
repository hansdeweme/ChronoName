# duplicate_core.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
#  wrapper for DedupTool engine
#

from __future__ import annotations
import copy
from pathlib import Path
# local imports
from deduptool import DedupConfig, DedupEngine, load_settings, write_csv, write_html, execute_moves
from models import DuplicateOptions, DuplicateResult
from report_paths import report_dir_for, report_path, report_timestamp, REPORTS_FOLDER_NAME

QUARANTINE_FOLDER_NAME = ".quarantine"


def _raise_if_cancelled(options: DuplicateOptions) -> None:
    if options.cancel_callback and options.cancel_callback():
        raise RuntimeError("Operation cancelled.")


def run_duplicate_detection(options: DuplicateOptions) -> DuplicateResult:
    _raise_if_cancelled(options)
    roots = [str(path.resolve()) for path in options.roots]
    if not roots:
        raise ValueError("At least one duplicate scan root is required.")

    for root in options.roots:
        if not root.exists():
            raise FileNotFoundError(f"Not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

    report_dir = report_dir_for(options.report_dir or options.roots[0])

    cfg = DedupConfig(
        max_workers=options.max_workers,
        html_thumb_side=options.html_thumb_side,
    )
    cfg.do_exact_hash = options.do_exact_hash

    def log(message: str) -> None:
        if options.log_callback:
            options.log_callback(message)

    def progress(done: int, total: int, phase: str) -> None:
        _raise_if_cancelled(options)
        if options.progress_callback:
            options.progress_callback(phase, done, total, phase)

    def move_progress(done: int) -> None:
        _raise_if_cancelled(options)

        total = len(summary.get("to_drop", []))

        if options.progress_callback:
            options.progress_callback(
                "moving",
                done,
                total,
                "moving duplicate files",
            )

    engine = DedupEngine(cfg, log=log, progress=progress)
    engine.settings = build_duplicate_scan_settings(options, report_dir)
    _raise_if_cancelled(options)
    summary = engine.plan(roots)
    _raise_if_cancelled(options)

    report_dir.mkdir(parents=True, exist_ok=True)
    report_ts = report_timestamp()

    csv_path = None
    if options.write_csv:
        _raise_if_cancelled(options)
        csv_path = report_path(options.report_dir or options.roots[0], "duplicate_report", report_ts, "csv")
        write_csv(summary, str(csv_path), roots)

    html_path = None
    if options.write_html and summary.get("clusters", 0) > 0:
        _raise_if_cancelled(options)
        html_path = report_path(options.report_dir or options.roots[0], "duplicate_report", report_ts, "html")
        write_html(
            summary,
            str(html_path),
            roots,
            thumb_side=options.html_thumb_side,
        )

    actions = {
        "moved": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
    }
    if options.quarantine_duplicates:
        _raise_if_cancelled(options)
        actions = execute_moves(
            summary,
            quarantine_dir=str(options.quarantine_dir) if options.quarantine_dir else "",
            roots=roots,
            use_trash=options.use_trash,
            dry_run=options.dry_run,
            log=log,
            progress = move_progress,
        )

    return DuplicateResult(
        files_scanned=int(summary.get("files", 0)),
        clusters=int(summary.get("clusters", 0)),
        keep_count=len(summary.get("to_keep", [])),
        drop_count=len(summary.get("to_drop", [])),
        moved_count=int(actions.get("moved", 0)),
        failed_count=int(actions.get("failed", 0)),
        csv_path=csv_path,
        html_path=html_path,
        quarantine_dir=options.quarantine_dir,
    )


def build_duplicate_scan_settings(options: DuplicateOptions, report_dir: Path) -> dict:
    settings = copy.deepcopy(load_settings())
    scan_settings = settings.setdefault("scan", {})
    exclude_names = scan_settings.setdefault("exclude_dirnames", [])
    if REPORTS_FOLDER_NAME not in exclude_names:
        exclude_names.append(REPORTS_FOLDER_NAME)
    if QUARANTINE_FOLDER_NAME not in exclude_names:
        exclude_names.append(QUARANTINE_FOLDER_NAME)
    configured_excludes = scan_settings.setdefault("exclude_dirpaths", [])
    configured_excludes.append(str(report_dir.resolve()))
    if options.exclude_dirs:
        configured_excludes.extend(str(path.resolve()) for path in options.exclude_dirs)
    return settings

