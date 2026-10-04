# timestamp_health.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# Source-folder timestamp health audit.
#

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo
# local imports
from chrononame_core import (
    already_good_name,
    evaluate_timestamp_decision,
    first_capture_datetime as core_first_capture_datetime,
    parse_exif_dt,
    parse_filename_datetime,
    scan_metadata,
)
from exiftool_adapter import SUPPORTED_EXT
from models import (RenameOptions, TimestampHealthAuditItem, TimestampHealthAuditResult,)
from report_paths import timestamped_report_path

def run_timestamp_health_audit(options: RenameOptions) -> TimestampHealthAuditResult:
    data = scan_metadata(options)
    name_tz = ZoneInfo(options.name_tz)
    items: list[TimestampHealthAuditItem] = []
    source_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    ready_count = 0
    review_count = 0
    skipped_count = 0

    total = len(data)
    progress_every = max(1, int(options.progress_every or 100))

    for index, meta in enumerate(data, start=1):
        if options.cancel_callback and options.cancel_callback():
            raise RuntimeError("Operation cancelled.")
        item = build_timestamp_health_item(meta, name_tz)
        items.append(item)
        source_counts[item.timestamp_source] += 1
        confidence_counts[item.confidence] += 1
        if item.warning:
            for warning in item.warning.split("; "):
                warning_counts[warning] += 1

        if item.confidence.startswith("high") or item.confidence.startswith("medium"):
            ready_count += 1
        elif item.confidence == "skip":
            skipped_count += 1
        else:
            review_count += 1

        if options.progress_callback and (index % progress_every == 0 or index == total):
            if options.cancel_callback and options.cancel_callback():
                raise RuntimeError("Operation cancelled.")
            options.progress_callback("health-audit", index, total, "auditing timestamp health")

    csv_path = timestamped_report_path(options.root, "timestamp_health_audit", "csv")
    write_timestamp_health_csv(items, csv_path)

    return TimestampHealthAuditResult(
        root=options.root,
        scanned_count=len(data),
        supported_count=sum(1 for item in items if item.confidence != "skip"),
        ready_count=ready_count,
        review_count=review_count,
        skipped_count=skipped_count,
        source_counts=dict(source_counts),
        confidence_counts=dict(confidence_counts),
        warning_counts=dict(warning_counts),
        items=items,
        csv_path=csv_path,
    )


def build_timestamp_health_item(meta: dict, name_tz: ZoneInfo) -> TimestampHealthAuditItem:
    path = Path(meta.get("SourceFile") or (Path(meta["Directory"]) / meta["FileName"]))
    filename = path.name
    extension = path.suffix.lower()
    already_named = already_good_name(filename)
    warnings: list[str] = []

    if extension.lstrip(".") not in SUPPORTED_EXT:
        return TimestampHealthAuditItem(
            path=path,
            filename=filename,
            extension=extension,
            chosen_datetime=None,
            timestamp_source="unsupported_extension",
            confidence="skip",
            metadata_datetime=None,
            filename_datetime=parse_filename_datetime(filename),
            file_modify_datetime=parse_exif_dt(meta.get("FileModifyDate")),
            already_named=already_named,
            warning="unsupported_extension",
        )

    file_modify_datetime = parse_exif_dt(meta.get("FileModifyDate"))
    filename_datetime = parse_filename_datetime(filename)
    capture_datetime, _, _ = core_first_capture_datetime(meta)
    decision = evaluate_timestamp_decision(
        meta,
        path=path,
        name_tz=name_tz,
        include_filename=True,
        include_file_modify=True,
        already_named=already_named,
    )
    warnings.extend(decision.warnings)

    return TimestampHealthAuditItem(
        path=path,
        filename=filename,
        extension=extension,
        chosen_datetime=decision.chosen_datetime,
        timestamp_source=decision.source,
        confidence=decision.confidence,
        metadata_datetime=capture_datetime,
        filename_datetime=filename_datetime,
        file_modify_datetime=file_modify_datetime,
        already_named=already_named,
        warning="; ".join(warnings),
    )


def first_capture_datetime(meta: dict):
    dt, source, _ = core_first_capture_datetime(meta)
    return dt, source


def write_timestamp_health_csv(items: list[TimestampHealthAuditItem], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "path",
                "filename",
                "extension",
                "chosen_datetime",
                "timestamp_source",
                "confidence",
                "metadata_datetime",
                "filename_datetime",
                "file_modify_datetime",
                "already_named",
                "warning",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    str(item.path),
                    item.filename,
                    item.extension,
                    item.chosen_datetime.isoformat() if item.chosen_datetime else "",
                    item.timestamp_source,
                    item.confidence,
                    item.metadata_datetime.isoformat() if item.metadata_datetime else "",
                    item.filename_datetime.isoformat() if item.filename_datetime else "",
                    item.file_modify_datetime.isoformat() if item.file_modify_datetime else "",
                    item.already_named,
                    item.warning,
                ]
            )

