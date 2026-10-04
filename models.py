# models.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# shared dataclasses and typed boundaries.
#

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]

@dataclass
class RenameOptions:
    root: Path
    name_tz: str = "Europe/Amsterdam"
    dry_run: bool = False
    include_device: bool = False
    skip_already: bool = False
    log_path: Path | None = None
    write_manifest: bool = False
    manifest_path: Path | None = None
    manifest_hash: bool = False
    progress_every: int = 100
    show_progress: bool = True
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None

@dataclass
class RenameOperation:
    old_path: Path
    new_path: Path
    timestamp_source: str
    source_size: int | None = None
    source_mtime_ns: int | None = None

    def to_log_entry(self) -> dict:
        entry = {
            "old": str(self.old_path),
            "new": str(self.new_path),
            "source": self.timestamp_source,
        }
        if self.source_size is not None:
            entry["source_size"] = self.source_size
        if self.source_mtime_ns is not None:
            entry["source_mtime_ns"] = self.source_mtime_ns
        return entry

    @classmethod
    def from_log_entry(cls, entry: dict) -> "RenameOperation":
        return cls(
            old_path=Path(entry["old"]),
            new_path=Path(entry["new"]),
            timestamp_source=str(entry.get("source") or ""),
            source_size=entry.get("source_size"),
            source_mtime_ns=entry.get("source_mtime_ns"),
        )

@dataclass
class ManifestPlanEntry:
    old_path: Path
    new_path: Path
    old_name: str
    dt: datetime
    source: str
    meta: dict

@dataclass
class TimestampDecision:
    chosen_datetime: datetime | None
    source: str
    confidence: str
    warnings: list[str]
    rejected_candidates: list[str]

@dataclass
class ChronoNameFilename:
    datetime: datetime
    milliseconds: int | None = None
    device: str = ""
    collision_counter: int | None = None
    extension: str = ""

@dataclass
class RenamePlan:
    root: Path
    operations: list[RenameOperation]
    manifest_entries: list[ManifestPlanEntry]
    metadata_count: int
    skipped_count: int
    name_tz: str

@dataclass
class RenameResult:
    planned_count: int
    renamed_count: int
    skipped: list[str]
    operations: list[RenameOperation]
    log_path: Path | None = None
    journal_path: Path | None = None
    manifest_path: Path | None = None

@dataclass
class UndoResult:
    undone_count: int
    skipped: list[str]


@dataclass
class DuplicateOptions:
    roots: list[Path]
    exclude_dirs: list[Path] = field(default_factory=list)
    dry_run: bool = True
    quarantine_duplicates: bool = False
    quarantine_dir: Path | None = None
    use_trash: bool = False
    write_csv: bool = True
    write_html: bool = True
    report_dir: Path | None = None
    html_thumb_side: int = 240
    max_workers: int = 16
    do_exact_hash: bool = False
    progress_callback: ProgressCallback | None = None
    log_callback: Callable[[str], None] | None = None
    cancel_callback: CancelCallback | None = None


@dataclass
class DuplicateResult:
    files_scanned: int
    clusters: int
    keep_count: int
    drop_count: int
    moved_count: int
    failed_count: int
    csv_path: Path | None = None
    html_path: Path | None = None
    quarantine_dir: Path | None = None


@dataclass
class TimestampHealthAuditItem:
    path: Path
    filename: str
    extension: str
    chosen_datetime: datetime | None
    timestamp_source: str
    confidence: str
    metadata_datetime: datetime | None
    filename_datetime: datetime | None
    file_modify_datetime: datetime | None
    already_named: bool
    warning: str


@dataclass
class TimestampHealthAuditResult:
    root: Path
    scanned_count: int
    supported_count: int
    ready_count: int
    review_count: int
    skipped_count: int
    source_counts: dict[str, int]
    confidence_counts: dict[str, int]
    warning_counts: dict[str, int]
    items: list[TimestampHealthAuditItem]
    csv_path: Path | None = None


@dataclass
class FilingAuditOptions:
    root: Path
    tolerance_days: int = 1
    cross_year_forward_days: int = 14
    ignored_folder_names: list[str] = field(default_factory=list)
    progress_every: int = 250
    show_progress: bool = True
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None


@dataclass
class FilingAuditItem:
    reason: str
    file_date: str
    file_path: Path
    checked_against: str
    allowed_range: str


@dataclass
class FilingFolderAnomaly:
    folder: Path
    range: str
    reason: str


@dataclass
class FilingAuditResult:
    root: Path
    mode: str
    scanned_count: int
    supported_count: int
    anomaly_count: int
    not_chrononame_count: int
    folder_anomaly_count: int
    csv_path: Path | None = None
    folder_csv_path: Path | None = None
    items: list[FilingAuditItem] = field(default_factory=list)
    folder_anomalies: list[FilingFolderAnomaly] = field(default_factory=list)


class WhatsAppSentCategory(StrEnum):
    GALLERY_ATTACHMENT = "Gallery_Attachments"
    IN_APP_CAMERA = "In_App_Camera"
    UNCLASSIFIED_OR_CROPPED = "Unclassified_or_Cropped"
    RECEIVED = "Received"


class WhatsAppWorkflowAction(StrEnum):
    MATCH_ORIGINAL_FIRST = "match_original_first"
    IMPORT_CANDIDATE = "import_candidate"
    REVIEW_REQUIRED = "review_required"


class WhatsAppDateConfidence(StrEnum):
    HIGH_MATCHED_ORIGINAL = "high_matched_original"
    HIGH_EMBEDDED_METADATA = "high_embedded_metadata"
    MEDIUM_TENTATIVE_TIME = "medium_tentative_time"
    MEDIUM_DATE_ONLY = "medium_date_only"
    LOW_FILE_MODIFY_ONLY = "low_file_modify_only"
    UNKNOWN = "unknown"


@dataclass
class WhatsAppImageSignature:
    path: Path
    width: int
    height: int
    has_exif: bool
    category: WhatsAppSentCategory

    @property
    def aspect_ratio(self) -> float:
        return max(self.width, self.height) / min(self.width, self.height)


@dataclass
class WhatsAppAnalysisResult:
    root: Path
    scanned_count: int
    error_count: int
    signatures: list[WhatsAppImageSignature]

    def category_counts(self) -> dict[WhatsAppSentCategory, int]:
        counts = {category: 0 for category in WhatsAppSentCategory}
        for signature in self.signatures:
            counts[signature.category] += 1
        return counts


@dataclass
class WhatsAppProcessOptions:
    source_folder: Path
    target_folders: dict[WhatsAppSentCategory, Path]
    skip_existing: bool = True
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None


@dataclass
class WhatsAppProcessResult:
    analysis: WhatsAppAnalysisResult
    copied_count: int
    skipped_existing_count: int
    error_count: int
    target_folders: dict[WhatsAppSentCategory, Path]


@dataclass
class WhatsAppChronoPlanOptions:
    category_folders: dict[WhatsAppSentCategory, Path]
    report_path: Path | None = None
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None


@dataclass
class WhatsAppChronoPlanItem:
    path: Path
    category: WhatsAppSentCategory
    action: WhatsAppWorkflowAction
    filename_date: datetime | None
    file_modify_datetime: datetime | None
    chosen_datetime: datetime | None
    date_source: str
    confidence: WhatsAppDateConfidence
    note: str


@dataclass
class WhatsAppChronoPlanResult:
    items: list[WhatsAppChronoPlanItem]
    report_path: Path | None = None

    def action_counts(self) -> dict[WhatsAppWorkflowAction, int]:
        counts = {action: 0 for action in WhatsAppWorkflowAction}
        for item in self.items:
            counts[item.action] += 1
        return counts

    def confidence_counts(self) -> dict[WhatsAppDateConfidence, int]:
        counts = {confidence: 0 for confidence in WhatsAppDateConfidence}
        for item in self.items:
            counts[item.confidence] += 1
        return counts

