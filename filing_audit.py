# filing_audit.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# Report-only archive filing audit based on ChronoName filename dates.
#

from __future__ import annotations

import csv
import os
import re
from datetime import date, timedelta
from pathlib import Path

from chrononame_core import parse_chrononame_filename
from exiftool_adapter import SUPPORTED_EXT
from models import (
    FilingAuditItem,
    FilingAuditOptions,
    FilingAuditResult,
    FilingFolderAnomaly,
)
from report_paths import REPORTS_FOLDER_NAME, report_path, report_timestamp


FOLDER_RE = re.compile(
    r"^(?P<start>\d{8})(?:_(?P<end>\d{8}))?(?:-.+)?$",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"^\d{4}$")


def run_filing_audit(options: FilingAuditOptions) -> FilingAuditResult:
    root = options.root
    if not root.exists():
        raise FileNotFoundError(f"Not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    year = _selected_year(root)
    mode = "year_root" if year is not None else "general_root"
    ignored_names = {name.lower() for name in options.ignored_folder_names}
    ignored_names.add(REPORTS_FOLDER_NAME.lower())

    folder_ranges = collect_dated_folder_ranges(root, ignored_names, options)
    folder_anomalies = analyze_folder_ranges(root, folder_ranges, year, options)
    items: list[FilingAuditItem] = []

    scanned_count = 0
    supported_count = 0
    not_chrononame_count = 0
    progress_every = max(1, int(options.progress_every or 250))

    for directory, _, filenames in os_walk(root, ignored_names, options):
        for filename in filenames:
            _raise_if_cancelled(options)
            scanned_count += 1
            path = directory / filename
            if path.suffix.lower().lstrip(".") not in SUPPORTED_EXT:
                continue
            supported_count += 1

            parsed = parse_chrononame_filename(path.name)
            if parsed is None:
                not_chrononame_count += 1
                items.append(
                    FilingAuditItem(
                        reason="NotChronoNameFormatted",
                        file_date="",
                        file_path=path,
                        checked_against="",
                        allowed_range="",
                    )
                )
                _emit_progress(options, supported_count, progress_every)
                continue

            file_date = parsed.datetime.date()
            ancestor, folder_range = nearest_ancestor_range(directory, folder_ranges)
            if ancestor is not None and folder_range is not None:
                allowed = constrained_folder_range(folder_range, options)
                if not _date_in_allowed_range(file_date, allowed, options.tolerance_days):
                    items.append(
                        FilingAuditItem(
                            reason="FileDateOutsideFolderDateRange",
                            file_date=file_date.isoformat(),
                            file_path=path,
                            checked_against=str(ancestor),
                            allowed_range=_format_range(allowed),
                        )
                    )
                _emit_progress(options, supported_count, progress_every)
                continue

            if year is not None:
                allowed = (
                    date(year, 1, 1) - timedelta(days=options.tolerance_days),
                    date(year, 12, 31) + timedelta(days=options.tolerance_days),
                )
                if not (allowed[0] <= file_date <= allowed[1]):
                    items.append(
                        FilingAuditItem(
                            reason="FileDateOutsideSelectedYearFolder",
                            file_date=file_date.isoformat(),
                            file_path=path,
                            checked_against=str(root),
                            allowed_range=_format_range(allowed),
                        )
                    )

            _emit_progress(options, supported_count, progress_every)

    timestamp = report_timestamp()
    csv_path = report_path(root, "filing_audit", timestamp, "csv")
    folder_csv_path = report_path(root, "filing_folder_anomalies", timestamp, "csv")
    write_filing_audit_csv(items, csv_path)
    write_folder_anomaly_csv(folder_anomalies, folder_csv_path)

    return FilingAuditResult(
        root=root,
        mode=mode,
        scanned_count=scanned_count,
        supported_count=supported_count,
        anomaly_count=len(items),
        not_chrononame_count=not_chrononame_count,
        folder_anomaly_count=len(folder_anomalies),
        csv_path=csv_path,
        folder_csv_path=folder_csv_path,
        items=items,
        folder_anomalies=folder_anomalies,
    )


def parse_folder_range_from_name(name: str) -> tuple[date, date] | None:
    match = FOLDER_RE.match(name)
    if not match:
        return None
    try:
        start = _yyyymmdd_to_date(match.group("start"))
        end = _yyyymmdd_to_date(match.group("end")) if match.group("end") else start
    except ValueError:
        return None
    if end < start:
        return end, start
    return start, end


def collect_dated_folder_ranges(
    root: Path,
    ignored_names: set[str],
    options: FilingAuditOptions,
) -> dict[Path, tuple[date, date]]:
    ranges: dict[Path, tuple[date, date]] = {}
    for directory, _, _ in os_walk(root, ignored_names, options):
        parsed = parse_folder_range_from_name(directory.name)
        if parsed:
            ranges[directory] = parsed
    return ranges


def nearest_ancestor_range(
    path: Path,
    ranges: dict[Path, tuple[date, date]],
) -> tuple[Path | None, tuple[date, date] | None]:
    current = path
    while current.parent != current:
        if current in ranges:
            return current, ranges[current]
        current = current.parent
    return None, None


def analyze_folder_ranges(
    root: Path,
    ranges: dict[Path, tuple[date, date]],
    year: int | None,
    options: FilingAuditOptions,
) -> list[FilingFolderAnomaly]:
    anomalies: list[FilingFolderAnomaly] = []
    for folder, folder_range in ranges.items():
        start, end = folder_range
        if folder == root:
            continue

        if _is_cross_year_forward_range(folder_range):
            limit = date(start.year + 1, 1, 1) + timedelta(days=options.cross_year_forward_days)
            if end > limit:
                anomalies.append(
                    FilingFolderAnomaly(
                        folder=folder,
                        range=_format_range(folder_range),
                        reason="CrossYearRangeBeyondAllowedForwardSpillover",
                    )
                )

        if year is None:
            continue

        if start.year < year:
            anomalies.append(
                FilingFolderAnomaly(
                    folder=folder,
                    range=_format_range(folder_range),
                    reason="FolderDateRangeStartsBeforeSelectedYear",
                )
            )
        elif start.year > year:
            anomalies.append(
                FilingFolderAnomaly(
                    folder=folder,
                    range=_format_range(folder_range),
                    reason="FolderDateRangeStartsAfterSelectedYear",
                )
            )

        if (start.year < year and end.year < year) or (start.year > year and end.year > year):
            anomalies.append(
                FilingFolderAnomaly(
                    folder=folder,
                    range=_format_range(folder_range),
                    reason="FolderDateRangeOutsideSelectedYear",
                )
            )

    return anomalies


def constrained_folder_range(
    folder_range: tuple[date, date],
    options: FilingAuditOptions,
) -> tuple[date, date]:
    start, end = folder_range
    if _is_cross_year_forward_range(folder_range):
        limit = date(start.year + 1, 1, 1) + timedelta(days=options.cross_year_forward_days)
        return start, min(end, limit)
    return folder_range


def os_walk(root: Path, ignored_names: set[str], options: FilingAuditOptions):
    for dirpath, dirnames, filenames in os.walk(root):
        _raise_if_cancelled(options)
        dirnames[:] = [name for name in dirnames if name.lower() not in ignored_names]
        directory = Path(dirpath)
        yield directory, [directory / name for name in dirnames], filenames


def write_filing_audit_csv(items: list[FilingAuditItem], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["reason", "file_date", "file_path", "checked_against", "allowed_range"],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "reason": item.reason,
                    "file_date": item.file_date,
                    "file_path": str(item.file_path),
                    "checked_against": item.checked_against,
                    "allowed_range": item.allowed_range,
                }
            )


def write_folder_anomaly_csv(items: list[FilingFolderAnomaly], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["folder", "range", "reason"])
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "folder": str(item.folder),
                    "range": item.range,
                    "reason": item.reason,
                }
            )


def _date_in_allowed_range(
    value: date,
    allowed: tuple[date, date],
    tolerance_days: int,
) -> bool:
    tolerance = timedelta(days=tolerance_days)
    return allowed[0] - tolerance <= value <= allowed[1] + tolerance


def _emit_progress(options: FilingAuditOptions, supported_count: int, progress_every: int) -> None:
    if options.progress_callback and supported_count % progress_every == 0:
        options.progress_callback(
            "filing-audit",
            0,
            0,
            f"scanned {supported_count} supported media files",
        )


def _is_cross_year_forward_range(folder_range: tuple[date, date]) -> bool:
    start, end = folder_range
    return start.year + 1 == end.year


def _format_range(value: tuple[date, date]) -> str:
    return f"{value[0].isoformat()}..{value[1].isoformat()}"


def _selected_year(root: Path) -> int | None:
    if not YEAR_RE.match(root.name):
        return None
    year = int(root.name)
    if 1 <= year <= 9999:
        return year
    return None


def _yyyymmdd_to_date(value: str) -> date:
    return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))


def _raise_if_cancelled(options: FilingAuditOptions) -> None:
    if options.cancel_callback and options.cancel_callback():
        raise RuntimeError("Operation cancelled.")

