# workers.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# worker-thread execution
#

from __future__ import annotations
from pathlib import Path
# PyQt6 imports
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
# local imports
from chrononame_core import build_rename_plan, execute_rename_plan, undo_renames
from diagnostics_core import run_core_diagnostics
from duplicate_core import run_duplicate_detection
from filing_audit import run_filing_audit
from timestamp_health import run_timestamp_health_audit
from models import (
    DuplicateOptions,
    FilingAuditOptions,
    RenameOptions,
    RenamePlan,
    WhatsAppChronoPlanOptions,
    WhatsAppProcessOptions,
)
from whatsapp_core import (
    analyze_whatsapp_received_folder,
    analyze_whatsapp_sent_folder,
    plan_whatsapp_chrononame_workflow,
    process_whatsapp_sent_folder,
)

class ChronoNameWorker(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    plan_ready = pyqtSignal(object)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        mode: str,
        options: RenameOptions | None = None,
        plan: RenamePlan | None = None,
        duplicate_options: DuplicateOptions | None = None,
        filing_audit_options: FilingAuditOptions | None = None,
        whatsapp_root: Path | None = None,
        whatsapp_process_options: WhatsAppProcessOptions | None = None,
        whatsapp_chrono_options: WhatsAppChronoPlanOptions | None = None,
        undo_log_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.options = options
        self.plan = plan
        self.duplicate_options = duplicate_options
        self.filing_audit_options = filing_audit_options
        self.whatsapp_root = whatsapp_root
        self.whatsapp_process_options = whatsapp_process_options
        self.whatsapp_chrono_options = whatsapp_chrono_options
        self.undo_log_path = undo_log_path
        self._cancel_requested = False
        if self.options:
            self.options.progress_callback = self._progress_callback
            self.options.cancel_callback = self.is_cancel_requested
        if self.duplicate_options:
            self.duplicate_options.progress_callback = self._progress_callback
            self.duplicate_options.log_callback = self.log.emit
            self.duplicate_options.cancel_callback = self.is_cancel_requested
        if self.filing_audit_options:
            self.filing_audit_options.progress_callback = self._progress_callback
            self.filing_audit_options.cancel_callback = self.is_cancel_requested
        if self.whatsapp_process_options:
            self.whatsapp_process_options.progress_callback = self._progress_callback
            self.whatsapp_process_options.cancel_callback = self.is_cancel_requested
        if self.whatsapp_chrono_options:
            self.whatsapp_chrono_options.progress_callback = self._progress_callback
            self.whatsapp_chrono_options.cancel_callback = self.is_cancel_requested

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self.mode == "analyze":
                if self.options is None:
                    raise RuntimeError("No rename options are available.")
                self.log.emit(f"Planning rename for folder: {self.options.root}")
                plan = build_rename_plan(self.options)
                self.plan_ready.emit(plan)
                self.progress.emit(100)
                self.status.emit("Rename plan complete.")
                return

            if self.mode == "health_audit":
                if self.options is None:
                    raise RuntimeError("No timestamp health audit options are available.")
                self.log.emit(f"Auditing timestamp health: {self.options.root}")
                result = run_timestamp_health_audit(self.options)
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("Timestamp health audit complete.")
                return

            if self.mode == "process":
                if self.options is None:
                    raise RuntimeError("No rename options are available.")
                if self.plan is None:
                    raise RuntimeError("No rename plan is available to process.")
                self.log.emit(f"Processing {len(self.plan.operations)} planned rename operations.")
                result = execute_rename_plan(self.plan, self.options)
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("Processing complete.")
                return

            if self.mode == "duplicates":
                if self.duplicate_options is None:
                    raise RuntimeError("No duplicate detection options are available.")
                if self.duplicate_options.quarantine_duplicates:
                    self.log.emit("Finding and quarantining duplicate files.")
                else:
                    self.log.emit("Creating duplicate report.")
                result = run_duplicate_detection(self.duplicate_options)
                self.result_ready.emit(result)
                self.progress.emit(100)
                if self.duplicate_options.quarantine_duplicates:
                    self.status.emit("Duplicate quarantine complete.")
                else:
                    self.status.emit("Duplicate report complete.")
                return

            if self.mode == "diagnostics":
                self.log.emit("Running ChronoName core diagnostics.")
                result = run_core_diagnostics()
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("Core diagnostics complete.")
                return

            if self.mode == "filing_audit":
                if self.filing_audit_options is None:
                    raise RuntimeError("No filing audit options are available.")
                self.log.emit(f"Auditing filing by filename date: {self.filing_audit_options.root}")
                result = run_filing_audit(self.filing_audit_options)
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("Filing audit complete.")
                return

            if self.mode == "undo":
                if self.undo_log_path is None:
                    raise RuntimeError("No undo log is available.")
                self.log.emit(f"Undoing rename run from: {self.undo_log_path}")
                result = undo_renames(self.undo_log_path, cancel_callback=self.is_cancel_requested)
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("Undo complete.")
                return

            if self.mode == "whatsapp_sent":
                if self.whatsapp_root is None:
                    raise RuntimeError("No WhatsApp sent folder is available.")
                self.log.emit(f"Analyzing WhatsApp sent folder: {self.whatsapp_root}")
                result = analyze_whatsapp_sent_folder(
                    self.whatsapp_root,
                    progress_callback=self._progress_callback,
                    cancel_callback=self.is_cancel_requested,
                )
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("WhatsApp sent analysis complete.")
                return

            if self.mode == "whatsapp_received":
                if self.whatsapp_root is None:
                    raise RuntimeError("No WhatsApp received folder is available.")
                self.log.emit(f"Analyzing WhatsApp received folder: {self.whatsapp_root}")
                result = analyze_whatsapp_received_folder(
                    self.whatsapp_root,
                    progress_callback=self._progress_callback,
                    cancel_callback=self.is_cancel_requested,
                )
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("WhatsApp received analysis complete.")
                return

            if self.mode == "whatsapp_process":
                if self.whatsapp_process_options is None:
                    raise RuntimeError("No WhatsApp process options are available.")
                self.log.emit(
                    f"Preparing WhatsApp sent subfolders: "
                    f"{self.whatsapp_process_options.source_folder}"
                )
                result = process_whatsapp_sent_folder(self.whatsapp_process_options)
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("WhatsApp sent preparation finalizing...")
                return

            if self.mode == "whatsapp_chrono_plan":
                if self.whatsapp_chrono_options is None:
                    raise RuntimeError("No WhatsApp import plan options are available.")
                self.log.emit("Planning WhatsApp import workflow.")
                result = plan_whatsapp_chrononame_workflow(self.whatsapp_chrono_options)
                self.result_ready.emit(result)
                self.progress.emit(100)
                self.status.emit("WhatsApp import plan complete.")
                return

            raise RuntimeError(f"Unknown worker mode: {self.mode}")
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def _progress_callback(self, stage: str, done: int, total: int, message: str,) -> None:
        if self.is_cancel_requested():
            raise RuntimeError("Operation cancelled.")
        if total:
            self.progress.emit(round(done / total * 100))
        else:
            self.progress.emit(-1)
        self.status.emit(f"{stage}: {message}")

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancel_requested = True
        self.status.emit("Cancellation requested...")

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested

