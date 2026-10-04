# whatsapp_core.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# WhatsApp media analysis helpers.
#

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image
except ImportError:
    Image = None

from exiftool_adapter import _exiftool_bin, _subprocess_no_window_kwargs
from chrononame_core import evaluate_timestamp_decision
from models import (
    ManifestPlanEntry,
    ProgressCallback,
    RenameOperation,
    RenamePlan,
    WhatsAppAnalysisResult,
    WhatsAppChronoPlanItem,
    WhatsAppChronoPlanOptions,
    WhatsAppChronoPlanResult,
    WhatsAppDateConfidence,
    WhatsAppImageSignature,
    WhatsAppProcessOptions,
    WhatsAppProcessResult,
    WhatsAppSentCategory,
    WhatsAppWorkflowAction,
)
from report_paths import timestamped_report_path


WHATSAPP_IMAGE_EXTENSIONS = {".jpg", ".jpeg"}
WHATSAPP_FILENAME_RE = re.compile(r"^IMG-(\d{8})-WA\d+\.(jpe?g)$", re.IGNORECASE)


def _raise_if_cancelled(cancel_callback) -> None:
    if cancel_callback and cancel_callback():
        raise RuntimeError("Operation cancelled.")


def classify_whatsapp_sent_image(width: int, height: int) -> WhatsAppSentCategory:
    aspect_ratio = max(width, height) / min(width, height)

    if 1.31 <= aspect_ratio <= 1.35:
        return WhatsAppSentCategory.GALLERY_ATTACHMENT

    if aspect_ratio >= 1.70:
        return WhatsAppSentCategory.IN_APP_CAMERA

    return WhatsAppSentCategory.UNCLASSIFIED_OR_CROPPED

def iter_whatsapp_images(root: Path) -> Iterable[Path]:
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in WHATSAPP_IMAGE_EXTENSIONS:
            yield path

def parse_whatsapp_filename_date(path: Path) -> datetime | None:
    match = WHATSAPP_FILENAME_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError:
        return None


def parse_whatsapp_exif_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    match = re.match(
        r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})",
        text,
    )
    if not match:
        return None
    try:
        return datetime(*map(int, match.groups()))
    except ValueError:
        return None


def read_whatsapp_embedded_datetime(path: Path) -> datetime | None:
    if Image is None:
        return None

    try:
        with Image.open(path) as img:
            exif = img.getexif()
    except Exception:
        return None

    for tag in (36867, 36868, 306):
        dt = parse_whatsapp_exif_datetime(exif.get(tag))
        if dt:
            return dt
    return None


def read_whatsapp_image_info(path: Path) -> tuple[int, int, bool]:
    if Image is not None:
        with Image.open(path) as img:
            width, height = img.size
            has_exif = bool(img.getexif())
        return width, height, has_exif

    return read_whatsapp_image_info_with_exiftool(path)


def read_whatsapp_image_info_with_exiftool(path: Path) -> tuple[int, int, bool]:
    p = subprocess.run(
        [
            _exiftool_bin(),
            "-json",
            "-ImageWidth",
            "-ImageHeight",
            "-EXIF:all",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_subprocess_no_window_kwargs(),
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "").strip() or f"ExifTool failed for {path}")

    data = json.loads(p.stdout or "[]")
    if not data:
        raise RuntimeError(f"ExifTool returned no metadata for {path}")

    meta = data[0]
    width = int(meta["ImageWidth"])
    height = int(meta["ImageHeight"])
    non_exif_keys = {"SourceFile", "ImageWidth", "ImageHeight"}
    has_exif = any(key not in non_exif_keys for key in meta)
    return width, height, has_exif


def analyze_whatsapp_sent_folder(
    root: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_callback=None,
) -> WhatsAppAnalysisResult:
    if not root.exists():
        raise FileNotFoundError(f"Not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    paths = list(iter_whatsapp_images(root))
    total = len(paths)
    signatures: list[WhatsAppImageSignature] = []
    error_count = 0

    for index, path in enumerate(paths, start=1):
        _raise_if_cancelled(cancel_callback)
        try:
            width, height, has_exif = read_whatsapp_image_info(path)
        except Exception:
            error_count += 1
            continue

        signatures.append(
            WhatsAppImageSignature(
                path=path,
                width=width,
                height=height,
                has_exif=has_exif,
                category=classify_whatsapp_sent_image(width, height),
            )
        )

        if progress_callback and (index % 100 == 0 or index == total):
            progress_callback("whatsapp", index, total, "analyzing sent images")

    return WhatsAppAnalysisResult(
        root=root,
        scanned_count=len(signatures),
        error_count=error_count,
        signatures=signatures,
    )


def analyze_whatsapp_received_folder(
    root: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_callback=None,
) -> WhatsAppAnalysisResult:
    if not root.exists():
        raise FileNotFoundError(f"Not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    paths = list(iter_whatsapp_images(root))
    total = len(paths)
    signatures: list[WhatsAppImageSignature] = []
    error_count = 0

    for index, path in enumerate(paths, start=1):
        _raise_if_cancelled(cancel_callback)
        try:
            width, height, has_exif = read_whatsapp_image_info(path)
        except Exception:
            error_count += 1
            continue

        signatures.append(
            WhatsAppImageSignature(
                path=path,
                width=width,
                height=height,
                has_exif=has_exif,
                category=WhatsAppSentCategory.RECEIVED,
            )
        )

        if progress_callback and (index % 100 == 0 or index == total):
            progress_callback("whatsapp", index, total, "analyzing received images")

    return WhatsAppAnalysisResult(
        root=root,
        scanned_count=len(signatures),
        error_count=error_count,
        signatures=signatures,
    )


def process_whatsapp_sent_folder(
    options: WhatsAppProcessOptions,
) -> WhatsAppProcessResult:
    analysis = analyze_whatsapp_sent_folder(
        options.source_folder,
        progress_callback=options.progress_callback,
        cancel_callback=options.cancel_callback,
    )

    for target in options.target_folders.values():
        _raise_if_cancelled(options.cancel_callback)
        target.mkdir(parents=True, exist_ok=True)

    copied_count = 0
    skipped_existing_count = 0
    copy_error_count = 0
    total = len(analysis.signatures)

    for index, signature in enumerate(analysis.signatures, start=1):
        _raise_if_cancelled(options.cancel_callback)
        target_folder = options.target_folders[signature.category]
        destination = target_folder / signature.path.name

        if options.skip_existing and destination.exists():
            skipped_existing_count += 1
        else:
            try:
                shutil.copy2(signature.path, destination)
                copied_count += 1
            except Exception:
                copy_error_count += 1

        if options.progress_callback and (index % 100 == 0 or index == total):
            options.progress_callback("whatsapp-copy", index, total, "copying categorized images")

    return WhatsAppProcessResult(
        analysis=analysis,
        copied_count=copied_count,
        skipped_existing_count=skipped_existing_count,
        error_count=analysis.error_count + copy_error_count,
        target_folders=options.target_folders,
    )


def plan_whatsapp_chrononame_workflow(
    options: WhatsAppChronoPlanOptions,
) -> WhatsAppChronoPlanResult:
    items: list[WhatsAppChronoPlanItem] = []
    category_paths = [
        (category, path)
        for category, path in options.category_folders.items()
        if path.exists() and path.is_dir()
    ]
    total = sum(1 for _, folder in category_paths for _ in iter_whatsapp_images(folder))
    done = 0

    for category, folder in category_paths:
        for path in iter_whatsapp_images(folder):
            _raise_if_cancelled(options.cancel_callback)
            done += 1
            item = build_whatsapp_chrono_plan_item(path, category)
            items.append(item)
            if options.progress_callback and (done % 100 == 0 or done == total):
                options.progress_callback("whatsapp-plan", done, total, "planning WhatsApp workflow")

    report_path = options.report_path
    if report_path is None and category_paths:
        if (
            len(category_paths) == 1
            and category_paths[0][0] == WhatsAppSentCategory.RECEIVED
        ):
            report_path = timestamped_report_path(
                category_paths[0][1],
                "whatsapp_received_import_plan",
                "csv",
            )
        else:
            report_path = timestamped_report_path(
                category_paths[0][1].parent,
                "whatsapp_import_plan",
                "csv",
            )

    if report_path:
        _raise_if_cancelled(options.cancel_callback)
        write_whatsapp_chrono_plan_csv(items, report_path)

    return WhatsAppChronoPlanResult(items=items, report_path=report_path)


def build_rename_plan_from_whatsapp_chrono_result(
    result: WhatsAppChronoPlanResult,
    *,
    name_tz: str,
) -> RenamePlan:
    operations: list[RenameOperation] = []
    manifest_entries: list[ManifestPlanEntry] = []
    planned_paths: set[Path] = set()
    skipped_count = 0

    roots = {item.path.parent for item in result.items}
    root = next(iter(roots), Path.cwd()) if len(roots) == 1 else Path.cwd()

    for item in result.items:
        if item.chosen_datetime is None:
            skipped_count += 1
            continue
        if item.action != WhatsAppWorkflowAction.IMPORT_CANDIDATE:
            skipped_count += 1
            continue

        new_path = _whatsapp_chrononame_target(item.path, item.chosen_datetime, planned_paths)
        if item.path == new_path:
            skipped_count += 1
            continue

        planned_paths.add(new_path)
        source_stat = item.path.stat()
        operations.append(
            RenameOperation(
                old_path=item.path,
                new_path=new_path,
                timestamp_source=item.date_source,
                source_size=source_stat.st_size,
                source_mtime_ns=source_stat.st_mtime_ns,
            )
        )

    return RenamePlan(
        root=root,
        operations=operations,
        manifest_entries=manifest_entries,
        metadata_count=len(result.items),
        skipped_count=skipped_count,
        name_tz=name_tz,
    )


def _whatsapp_chrononame_target(
    path: Path,
    chosen_datetime: datetime,
    planned_paths: set[Path],
) -> Path:
    directory = path.parent
    ext = path.suffix
    base = chosen_datetime.strftime("%Y%m%d_%H%M%S")
    counter = 0

    while True:
        suffix = f"_{counter:03d}" if counter > 0 else ""
        candidate = directory / f"{base}{suffix}{ext}"
        if candidate == path or (not candidate.exists() and candidate not in planned_paths):
            return candidate
        counter += 1


def build_whatsapp_chrono_plan_item(
    path: Path,
    category: WhatsAppSentCategory,
) -> WhatsAppChronoPlanItem:
    filename_date = parse_whatsapp_filename_date(path)
    embedded_datetime = read_whatsapp_embedded_datetime(path)
    file_modify_datetime = datetime.fromtimestamp(path.stat().st_mtime)
    decision_meta = {
        "SourceFile": str(path),
        "Directory": str(path.parent),
        "FileName": path.name,
        "FileModifyDate": file_modify_datetime,
    }
    if embedded_datetime:
        decision_meta["DateTimeOriginal"] = embedded_datetime

    decision = evaluate_timestamp_decision(
        decision_meta,
        path=path,
        name_tz=datetime.now().astimezone().tzinfo,
        include_filename=True,
        include_file_modify=True,
    )
    chosen_datetime = decision.chosen_datetime
    date_source = _whatsapp_date_source(decision.source)
    confidence = _whatsapp_date_confidence(decision.confidence)
    note = _whatsapp_timestamp_note(
        decision_source=decision.source,
        filename_date=filename_date,
        embedded_datetime=embedded_datetime,
        file_modify_datetime=file_modify_datetime,
    )

    action = _workflow_action_for_category(category)
    if category == WhatsAppSentCategory.GALLERY_ATTACHMENT:
        note = _append_note(note, "Likely duplicate; match against archive originals before import.")
    elif category == WhatsAppSentCategory.IN_APP_CAMERA:
        note = _append_note(note, "Probably unique WhatsApp in-app camera image.")
    elif category == WhatsAppSentCategory.RECEIVED:
        if confidence == WhatsAppDateConfidence.HIGH_EMBEDDED_METADATA:
            note = _append_note(note, "Received WhatsApp image with embedded capture metadata.")
        else:
            note = _append_note(note, "Received WhatsApp image; probably unique to this archive, but date/time may be limited to filename date.")
    else:
        note = _append_note(note, "Category uncertain; review or duplicate-match first.")
    return WhatsAppChronoPlanItem(
        path=path,
        category=category,
        action=action,
        filename_date=filename_date,
        file_modify_datetime=file_modify_datetime,
        chosen_datetime=chosen_datetime,
        date_source=date_source,
        confidence=confidence,
        note=note,
    )


def _whatsapp_date_source(source: str) -> str:
    if source in {"DateTimeOriginal", "SubSecDateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate"}:
        return "embedded_datetime_original"
    if source == "filename_datetime":
        return "whatsapp_filename_date"
    if source == "FileModifyDate":
        return "filemodify_only"
    return source if source != "none" else "unknown"


def _whatsapp_date_confidence(confidence: str) -> WhatsAppDateConfidence:
    if confidence in {"high_embedded_metadata", "high_video_metadata"}:
        return WhatsAppDateConfidence.HIGH_EMBEDDED_METADATA
    if confidence == "medium_tentative_time":
        return WhatsAppDateConfidence.MEDIUM_TENTATIVE_TIME
    if confidence == "medium_filename":
        return WhatsAppDateConfidence.MEDIUM_DATE_ONLY
    if confidence == "low_file_modify_only":
        return WhatsAppDateConfidence.LOW_FILE_MODIFY_ONLY
    return WhatsAppDateConfidence.UNKNOWN


def _whatsapp_timestamp_note(
    *,
    decision_source: str,
    filename_date: datetime | None,
    embedded_datetime: datetime | None,
    file_modify_datetime: datetime | None,
) -> str:
    if decision_source in {"DateTimeOriginal", "SubSecDateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate"}:
        if filename_date and embedded_datetime and embedded_datetime.date() != filename_date.date():
            delta_days = (embedded_datetime.date() - filename_date.date()).days
            return f"Embedded date differs from filename date by {delta_days} day(s)."
        return "Embedded capture datetime found."

    if decision_source == "filename_date+filemodify_time_same_day":
        return "Filename date agrees with FileModifyDate date; time is tentative."

    if decision_source == "filename_datetime":
        if filename_date and file_modify_datetime:
            delta_days = (file_modify_datetime.date() - filename_date.date()).days
            return f"FileModifyDate is {delta_days} day(s) after filename date."
        return "WhatsApp filename date found."

    if decision_source == "FileModifyDate":
        return "No WhatsApp filename date found."

    return "No usable timestamp found."

def write_whatsapp_chrono_plan_csv(items: list[WhatsAppChronoPlanItem], report_path: Path,) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "path",
                "filename",
                "category",
                "action",
                "filename_date",
                "file_modify_datetime",
                "chosen_datetime",
                "date_source",
                "confidence",
                "note",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    str(item.path),
                    item.path.name,
                    item.category.value,
                    item.action.value,
                    item.filename_date.isoformat() if item.filename_date else "",
                    item.file_modify_datetime.isoformat() if item.file_modify_datetime else "",
                    item.chosen_datetime.isoformat() if item.chosen_datetime else "",
                    item.date_source,
                    item.confidence.value,
                    item.note,
                ]
            )


def _workflow_action_for_category(category: WhatsAppSentCategory) -> WhatsAppWorkflowAction:
    if category == WhatsAppSentCategory.GALLERY_ATTACHMENT:
        return WhatsAppWorkflowAction.MATCH_ORIGINAL_FIRST
    if category in (WhatsAppSentCategory.IN_APP_CAMERA, WhatsAppSentCategory.RECEIVED):
        return WhatsAppWorkflowAction.IMPORT_CANDIDATE
    return WhatsAppWorkflowAction.REVIEW_REQUIRED


def _append_note(existing: str, addition: str) -> str:
    if not existing:
        return addition
    return f"{existing} {addition}"

