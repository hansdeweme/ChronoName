# ui.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# GUI for Chrononame
#

from __future__ import annotations
from pathlib import Path
# PyQt6 imports
from PyQt6.QtCore import QThread, Qt
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
# local imports
from config import AppConfig, _resource_path
from diagnostics_core import CoreDiagnosticsResult
from models import (
    DuplicateOptions,
    DuplicateResult,
    FilingAuditOptions,
    FilingAuditResult,
    RenameOptions,
    RenamePlan,
    RenameResult,
    TimestampHealthAuditResult,
    UndoResult,
    WhatsAppAnalysisResult,
    WhatsAppChronoPlanOptions,
    WhatsAppChronoPlanResult,
    WhatsAppProcessOptions,
    WhatsAppProcessResult,
    WhatsAppSentCategory,
)
from duplicate_core import QUARANTINE_FOLDER_NAME
from workers import ChronoNameWorker
from whatsapp_core import build_rename_plan_from_whatsapp_chrono_result
from version import VERSION as __version__


ICON_PATH = _resource_path("icon.png")


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle(config.app_name)
        self._apply_app_icon()
        self.resize(1160, 760)
        self.source_folder: Path | None = None
        self.current_plan: RenamePlan | None = None
        self.is_busy = False
        self.current_worker_mode: str | None = None
        self.worker_thread: QThread | None = None
        self.worker: ChronoNameWorker | None = None
        self._build_menu()
        self.setCentralWidget(self._build_content())
        self.statusBar().showMessage("Ready.")
        self.append_log("ChronoName desktop shell started.")

    def _apply_app_icon(self) -> None:
        if not ICON_PATH.exists():
            return
        icon = QIcon(str(ICON_PATH))
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)

    def _build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.setSpacing(6)

        self.safety_label = QLabel("No operation running. Choose a source folder, then start with Audit Timestamp Health.")
        self.safety_label.setObjectName("safetyLabel")
        self.safety_label.setWordWrap(True)
        self.safety_label.setMinimumHeight(28)
        self.safety_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_output.setPlaceholderText("ChronoName messages will appear here.")

        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(12)
        self.write_manifest_check = QCheckBox("Write collection manifest")
        self.manifest_hash_check = QCheckBox("Include hashes")
        self.manifest_hash_check.setToolTip("Include SHA-256 hashes in the manifest. This is slower.")
        self.manifest_hash_check.setEnabled(False)
        self.write_manifest_check.toggled.connect(self.manifest_hash_check.setEnabled)
        options_row.addWidget(self.write_manifest_check)
        options_row.addWidget(self.manifest_hash_check)
        options_row.addStretch(1)

        self.plan_table = QTableWidget(0, 6)
        self.plan_table.setHorizontalHeaderLabels(
            ["Current Name", "Planned Name", "Source", "Size", "Modified", "Folder"]
        )
        self.plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.verticalHeader().setVisible(False)
        header = self.plan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_label = QLabel("0%")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_label.setMinimumWidth(36)
        progress_row.addWidget(self.progress_bar, stretch=1)
        progress_row.addWidget(self.progress_label)

        layout.addWidget(self.safety_label)
        layout.addLayout(options_row)
        layout.addWidget(self.plan_table, stretch=2)
        layout.addWidget(self.log_output, stretch=1)
        layout.addLayout(progress_row)
        root.setStyleSheet(
            """
            QWidget {
                font-size: 13px;
            }
            QPlainTextEdit {
                border: 1px solid #cfcfcf;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
            }
            QLabel#safetyLabel {
                border: 1px solid #bdbdbd;
                background: #f7f7f7;
                color: #333333;
                padding: 5px 8px;
                font-weight: 600;
            }
            QProgressBar {
                min-height: 12px;
                max-height: 12px;
                border: 1px solid #bdbdbd;
                background: #f7f7f7;
            }
            """
        )
        return root

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        choose_source_action = QAction("Choose Source Folder...", self)
        choose_source_action.setShortcut("Ctrl+O")
        choose_source_action.setStatusTip("Choose the local folder that contains images to process.")
        choose_source_action.triggered.connect(self._choose_source_folder)
        file_menu.addAction(choose_source_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.setStatusTip("Close ChronoName.")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        workflow_menu = menu_bar.addMenu("&Workflow")
        self.health_audit_action = QAction("Audit Timestamp Health", self)
        self.health_audit_action.setEnabled(False)
        self.health_audit_action.setStatusTip("Review timestamp sources, confidence, and conflicts without changing files.")
        self.health_audit_action.triggered.connect(self._audit_timestamp_health)
        workflow_menu.addAction(self.health_audit_action)


        workflow_menu.addSeparator()
        self.duplicate_report_action = QAction("Create Duplicate Report", self)
        self.duplicate_report_action.setShortcut("Ctrl+D")
        self.duplicate_report_action.setEnabled(False)
        self.duplicate_report_action.setStatusTip("Create a visual duplicate report without moving files.")
        self.duplicate_report_action.triggered.connect(self._find_duplicates_report)
        workflow_menu.addAction(self.duplicate_report_action)

        self.duplicate_quarantine_action = QAction("Quarantine Duplicate Files", self)
        self.duplicate_quarantine_action.setEnabled(False)
        self.duplicate_quarantine_action.setStatusTip("Move files marked duplicate into a .quarantine folder in the selected source folder.")
        self.duplicate_quarantine_action.triggered.connect(self._quarantine_duplicates)
        workflow_menu.addAction(self.duplicate_quarantine_action)

        workflow_menu.addSeparator()
        self.analyze_action = QAction("Plan Rename", self)
        self.analyze_action.setShortcut("Ctrl+R")
        self.analyze_action.setEnabled(False)
        self.analyze_action.setStatusTip("Build a dry-run rename plan for the selected folder.")
        self.analyze_action.triggered.connect(self._analyze_folder)
        workflow_menu.addAction(self.analyze_action)

        self.process_action = QAction("Process Rename Plan", self)
        self.process_action.setShortcut("Ctrl+Enter")
        self.process_action.setEnabled(False)
        self.process_action.setStatusTip("Apply the reviewed rename plan and write an undo log.")
        self.process_action.triggered.connect(self._process_plan)
        workflow_menu.addAction(self.process_action)

        self.cancel_action = QAction("Cancel Current Operation", self)
        self.cancel_action.setShortcut("Esc")
        self.cancel_action.setEnabled(False)
        self.cancel_action.setStatusTip("Request cooperative cancellation of the active operation.")
        self.cancel_action.triggered.connect(self._cancel_current_operation)
        workflow_menu.addAction(self.cancel_action)

        self.undo_action = QAction("Undo Rename Run...", self)
        self.undo_action.setStatusTip("Undo a previous rename run from a JSON undo log or JSONL journal.")
        self.undo_action.triggered.connect(self._undo_rename_run)
        workflow_menu.addAction(self.undo_action)

        tools_menu = menu_bar.addMenu("&Tools")
        self.filing_audit_action = QAction("Audit Filing by Filename Date", self)
        self.filing_audit_action.setEnabled(True)
        self.filing_audit_action.setStatusTip("Validate archive filing against ChronoName filename dates without changing files.")
        self.filing_audit_action.triggered.connect(self._audit_filing_by_filename_date)
        tools_menu.addAction(self.filing_audit_action)

        self.core_diagnostics_action = QAction("Run Core Diagnostics...", self)
        self.core_diagnostics_action.setEnabled(True)
        self.core_diagnostics_action.setStatusTip("Verify packaged resources and run core ChronoName self-tests.")
        self.core_diagnostics_action.triggered.connect(self._run_core_diagnostics)
        tools_menu.addAction(self.core_diagnostics_action)

        workflow_menu.addSeparator()
        whatsapp_menu = workflow_menu.addMenu("WhatsApp")
        whatsapp_workflow_action = QAction("Show WhatsApp Notes", self)
        whatsapp_workflow_action.setStatusTip("Show the WhatsApp preparation workflow in the log.")
        whatsapp_workflow_action.triggered.connect(self._show_whatsapp_workflow)
        whatsapp_menu.addAction(whatsapp_workflow_action)     
        whatsapp_menu.addSeparator()          
        self.whatsapp_sent_action = QAction("Analyze Selected Sent Folder", self)
        self.whatsapp_sent_action.setEnabled(False)
        self.whatsapp_sent_action.setStatusTip("Classify selected WhatsApp sent images by image signature.")
        self.whatsapp_sent_action.triggered.connect(self._analyze_whatsapp_sent_folder)
        whatsapp_menu.addAction(self.whatsapp_sent_action)
        self.whatsapp_process_action = QAction("Prepare Configured Sent Subfolders", self)
        self.whatsapp_process_action.setStatusTip("Copy configured WhatsApp sent images into gallery, in-app, and review subfolders.")
        self.whatsapp_process_action.triggered.connect(self._process_whatsapp_sent_folder)
        whatsapp_menu.addAction(self.whatsapp_process_action)
        self.whatsapp_chrono_plan_action = QAction("Plan Configured Sent Import", self)
        self.whatsapp_chrono_plan_action.setStatusTip("Create a ChronoName plan for prepared WhatsApp sent subfolders.")
        self.whatsapp_chrono_plan_action.triggered.connect(self._plan_whatsapp_sent_workflow)
        whatsapp_menu.addAction(self.whatsapp_chrono_plan_action)        
        whatsapp_menu.addSeparator()                  
        self.whatsapp_received_action = QAction("Analyze Selected Received Folder", self)
        self.whatsapp_received_action.setEnabled(False)
        self.whatsapp_received_action.setStatusTip("Analyze selected WhatsApp received images as import candidates.")
        self.whatsapp_received_action.triggered.connect(self._analyze_whatsapp_received_folder)
        whatsapp_menu.addAction(self.whatsapp_received_action)
        self.whatsapp_received_plan_action = QAction("Plan Configured Received Import", self)
        self.whatsapp_received_plan_action.setStatusTip("Create a ChronoName plan directly from the configured WhatsApp received folder.")
        self.whatsapp_received_plan_action.triggered.connect(self._plan_whatsapp_received_workflow)
        whatsapp_menu.addAction(self.whatsapp_received_plan_action)
        self._update_configured_whatsapp_actions(busy=False)

        view_menu = menu_bar.addMenu("&View")
        clear_log_action = QAction("Clear Log", self)
        clear_log_action.setStatusTip("Clear messages from the log view.")
        clear_log_action.triggered.connect(self._clear_log)
        view_menu.addAction(clear_log_action)

        help_menu = menu_bar.addMenu("&Help")
        whatsapp_guide_action = QAction("WhatsApp Import Notes", self)
        whatsapp_guide_action.setStatusTip("Show basic guidance for preparing WhatsApp images.")
        whatsapp_guide_action.triggered.connect(self._show_whatsapp_notes)
        help_menu.addAction(whatsapp_guide_action)
        help_menu.addSeparator()

        about_action = QAction("About ChronoName", self)
        about_action.setStatusTip("Show ChronoName version information.")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _choose_source_folder(self) -> None:
        start = self._source_folder_dialog_start()
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose source folder",
            start,
        )
        if folder:
            self.source_folder = Path(folder).resolve()
            self.current_plan = None
            self._clear_plan_table()
            self.health_audit_action.setEnabled(True)
            self.analyze_action.setEnabled(True)
            self.duplicate_report_action.setEnabled(True)
            self.duplicate_quarantine_action.setEnabled(True)
            self.whatsapp_sent_action.setEnabled(True)
            self.whatsapp_received_action.setEnabled(True)
            self._update_process_action_enabled()
            self.statusBar().showMessage(f"Source folder selected: {self.source_folder}")
            self.append_log(f"Source folder selected: {self.source_folder}")
            self.set_safety_status(
                "REVIEW MODE: Source selected. Start with Audit Timestamp Health; no files have been changed.",
                "safe",
            )
            self.set_progress(0)

    def _source_folder_dialog_start(self) -> str:
        candidates: list[Path] = []
        if self.source_folder:
            candidates.append(self.source_folder)
        if self.config.default_source_folder:
            candidates.append(self._resolve_config_path(self.config.default_source_folder))
        candidates.append(Path.cwd())
        candidates.append(Path.home())

        for candidate in candidates:
            expanded = candidate.expanduser()
            if expanded.exists() and expanded.is_dir():
                return str(expanded)
        return str(Path.home())

    def _clear_log(self) -> None:
        self.log_output.clear()
        self.statusBar().showMessage("Log cleared.")

    def _show_whatsapp_notes(self) -> None:
        self.append_log("")
        self.append_log("WhatsApp import notes:")
        self.append_log("- Android users can copy WhatsApp media folders to a local source folder.")
        self.append_log("- iPhone users usually need to export chat media or otherwise copy files locally.")
        self.append_log("- ChronoName processing starts once images are available on this computer.")
        self.append_log("- Regular WhatsApp movies are heavily downgraded and usually not worth archiving.")        
        self.append_log("- Movies stored as WhatsApp Documents are not processed; treat these as normal media.")                
        self.statusBar().showMessage("WhatsApp import notes added to the log.")

    def _show_about(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("About ChronoName")
        dialog.setText(
            f"ChronoName {__version__}\n\n"
            "ChronoName is a local photo archive tool that audits capture timestamps, detects duplicates, safely renames media by capture date, and validates chronological filing—with planning, reporting, journaling, and undo built in."
        )
        if ICON_PATH.exists():
            icon = QIcon(str(ICON_PATH))
            dialog.setWindowIcon(icon)
            dialog.setIconPixmap(
                QPixmap(str(ICON_PATH)).scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            dialog.setIcon(QMessageBox.Icon.Information)
        dialog.exec()

    def _show_whatsapp_workflow(self) -> None:
        self.append_log("")
        self.append_log("WhatsApp workflow:")
        self.append_log("1. Locate WhatsApp image folders or export chat media.")
        self.append_log("2. Copy images into a local source folder (wa_sent / wa_received).")
        self.append_log("3. Choose File > Choose Source Folder.")
        self.append_log("4. Run Audit Timestamp Health to inspect timestamp confidence.")
        self.append_log("5. Create any duplicate or WhatsApp preparation reports needed.")
        self.append_log("6. Build and review a rename plan.")
        self.append_log("7. Process the rename plan and keep the undo log.")
        self.statusBar().showMessage("WhatsApp workflow added to the log.")

    def _analyze_folder(self) -> None:
        if self.source_folder is None:
            self.statusBar().showMessage("Choose a source folder first.")
            return
        options = self._build_options(dry_run=True)
        self.current_plan = None
        self.process_action.setEnabled(False)
        self._clear_plan_table()
        self.set_safety_status("PLAN ONLY: Building a dry-run rename plan. No files will be renamed.", "safe")
        self.set_progress(0)
        self._start_worker("analyze", options)

    def _audit_timestamp_health(self) -> None:
        if self.source_folder is None:
            self.statusBar().showMessage("Choose a source folder first.")
            return

        options = self._build_options(dry_run=True)
        self.set_safety_status("AUDIT ONLY: Inspecting timestamp health. No files will be changed.", "safe")
        self.set_progress(0)
        self._start_worker("health_audit", options)

    def _process_plan(self) -> None:
        if self.current_plan is None:
            self.statusBar().showMessage("Build a rename plan before processing.")
            return

        if not self._confirm_process_plan():
            self.statusBar().showMessage("Processing cancelled.")
            return

        options = self._build_options_for_root(self.current_plan.root, dry_run=False)
        self.set_safety_status("PROCESSING: Renaming files according to the reviewed plan. An undo log will be written.", "danger")
        self.set_progress(0)
        self._start_worker("process", options, self.current_plan)

    def _find_duplicates_report(self) -> None:
        if self.source_folder is None:
            self.statusBar().showMessage("Choose a source folder first.")
            return

        exclude_dirs = self._duplicate_scan_exclude_dirs()
        options = DuplicateOptions(
            roots=[self.source_folder],
            exclude_dirs=exclude_dirs,
            dry_run=True,
            quarantine_duplicates=False,
            write_csv=True,
            write_html=True,
            report_dir=self.source_folder,
        )
        if exclude_dirs:
            self.append_log("")
            self.append_log("Duplicate report will skip excluded folders:")
            for folder in exclude_dirs:
                self.append_log(f"  {folder}")
        self.append_log("")
        self.append_log("Creating duplicate report. No files will be moved or renamed.")
        self.set_safety_status("REPORT ONLY: Creating duplicate report. No files will be moved or renamed.", "safe")
        self.set_progress(0)
        self._start_worker("duplicates", duplicate_options=options)

    def _run_core_diagnostics(self) -> None:
        self.append_log("")
        self.append_log("Running ChronoName core diagnostics.")
        self.set_safety_status("DIAGNOSTICS: Checking runtime environment and core logic. No media files will be changed.", "safe")
        self.set_progress(0)
        self._start_worker("diagnostics")

    def _audit_filing_by_filename_date(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose archive folder to audit",
            self._source_folder_dialog_start(),
        )
        if not folder:
            self.statusBar().showMessage("Filing audit cancelled.")
            return

        audit_root = Path(folder).resolve()

        options = FilingAuditOptions(
            root=audit_root,
            tolerance_days=self.config.filing_audit.tolerance_days,
            cross_year_forward_days=self.config.filing_audit.cross_year_forward_days,
            ignored_folder_names=self.config.filing_audit.ignored_folder_names,
        )
        self.append_log("")
        self.append_log("Auditing filing by ChronoName filename date.")
        self.append_log(f"Archive folder: {audit_root}")
        self.append_log("Report only. No files will be moved or renamed.")
        self.set_safety_status("REPORT ONLY: Auditing filing by filename date. No files will be moved or renamed.", "safe")
        self.set_progress(0)
        self._start_worker("filing_audit", filing_audit_options=options)

    def _quarantine_duplicates(self) -> None:
        if self.source_folder is None:
            self.statusBar().showMessage("Choose a source folder first.")
            return

        quarantine_dir = self.source_folder / ".quarantine"
        if not self._confirm_duplicate_quarantine(quarantine_dir):
            self.statusBar().showMessage("Duplicate quarantine cancelled.")
            return

        exclude_dirs = self._duplicate_scan_exclude_dirs()
        options = DuplicateOptions(
            roots=[self.source_folder],
            exclude_dirs=exclude_dirs,
            dry_run=False,
            quarantine_duplicates=True,
            quarantine_dir=quarantine_dir,
            use_trash=False,
            write_csv=True,
            write_html=True,
            report_dir=self.source_folder,
        )
        if exclude_dirs:
            self.append_log("")
            self.append_log("Duplicate quarantine will skip excluded folders:")
            for folder in exclude_dirs:
                self.append_log(f"  {folder}")
        self.append_log("")
        self.append_log("Quarantining duplicate files.")
        self.append_log(f"Files marked duplicate will be moved to: {quarantine_dir}")
        self.set_safety_status("QUARANTINE: Moving duplicate files into the source .quarantine folder.", "danger")
        self.set_progress(0)
        self._start_worker("duplicates", duplicate_options=options)

    def _undo_rename_run(self) -> None:
        start = str(self.source_folder or Path.cwd())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose undo log",
            start,
            "Undo logs (*.json *.jsonl);;All files (*)",
        )
        if not selected:
            return

        undo_log_path = Path(selected)
        if not self._confirm_undo_run(undo_log_path):
            self.statusBar().showMessage("Undo cancelled.")
            return

        self.append_log("")
        self.append_log(f"Undoing rename run: {undo_log_path}")
        self.set_safety_status("UNDO: Restoring names from the selected undo log.", "warning")
        self.set_progress(0)
        self._start_worker("undo", undo_log_path=undo_log_path)

    def _cancel_current_operation(self) -> None:
        if self.worker is None:
            self.statusBar().showMessage("No operation is running.")
            return
        self.worker.cancel()
        self.cancel_action.setEnabled(False)
        self.set_safety_status("CANCELLING: Waiting for the active operation to stop safely.", "warning")
        self.statusBar().showMessage("Cancellation requested...")

    def _duplicate_scan_exclude_dirs(self) -> list[Path]:
        if self.source_folder is None:
            return []

        source = self.source_folder.resolve()
        excludes = []
        quarantine_dir = source / QUARANTINE_FOLDER_NAME
        if quarantine_dir.exists() and quarantine_dir.is_dir():
            excludes.append(quarantine_dir)

        whatsapp_sent = self._resolve_config_path(self.config.whatsapp_sent_folder)
        whatsapp_received = self._resolve_config_path(self.config.whatsapp_received_folder)
        if source not in (whatsapp_sent, whatsapp_received):
            return excludes

        category_folders = (
            self._whatsapp_sent_category_folders()
            if source == whatsapp_sent
            else self._whatsapp_received_category_folders()
        )
        for folder in category_folders.values():
            resolved = folder.resolve()
            if resolved.exists() and resolved.is_dir() and self._is_relative_to(resolved, source):
                excludes.append(resolved)
        return excludes

    def _is_relative_to(self, path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return path != parent
        except ValueError:
            return False

    def _analyze_whatsapp_sent_folder(self) -> None:
        if self.source_folder is None:
            self.statusBar().showMessage("Choose a source folder first.")
            return

        self.set_safety_status("ANALYSIS ONLY: Classifying selected WhatsApp sent images. No files will be changed.", "safe")
        self.set_progress(0)
        self._start_worker("whatsapp_sent", whatsapp_root=self.source_folder)

    def _analyze_whatsapp_received_folder(self) -> None:
        if self.source_folder is None:
            self.statusBar().showMessage("Choose a source folder first.")
            return

        self.set_safety_status("ANALYSIS ONLY: Inspecting selected WhatsApp received images. No files will be changed.", "safe")
        self.set_progress(0)
        self._start_worker("whatsapp_received", whatsapp_root=self.source_folder)

    def _process_whatsapp_sent_folder(self) -> None:
        options = WhatsAppProcessOptions(
            source_folder=self._resolve_config_path(self.config.whatsapp_sent_folder),
            target_folders=self._whatsapp_sent_category_folders(),
            skip_existing=True,
        )
        self.append_log("")
        self.append_log("Preparing WhatsApp sent subfolders using configured paths.")
        self.append_log("This copies files into preparation folders; originals are left in place.")
        self.set_safety_status("COPY PREPARATION: Copying WhatsApp sent files into subfolders. Originals stay in place.", "warning")
        self.append_log(f"Source: {options.source_folder}")
        for category, target in options.target_folders.items():
            self.append_log(f"{category.value}: {target}")
        self.set_progress(0)
        self._start_worker("whatsapp_process", whatsapp_process_options=options)

    def _plan_whatsapp_sent_workflow(self) -> None:
        options = WhatsAppChronoPlanOptions(category_folders=self._whatsapp_category_folders(),)
        self.append_log("")
        self.append_log("Planning WhatsApp sent import using configured category folders.")
        self.append_log("Planning only. No files will be renamed.")
        self.set_safety_status("PLAN ONLY: Building WhatsApp sent import plan. No files will be renamed.", "safe")
        for category, folder in options.category_folders.items():
            self.append_log(f"{category.value}: {folder}")
        self.set_progress(0)
        self._start_worker("whatsapp_chrono_plan", whatsapp_chrono_options=options)

    def _plan_whatsapp_received_workflow(self) -> None:
        options = WhatsAppChronoPlanOptions(
            category_folders=self._whatsapp_received_category_folders(),
        )
        self.append_log("")
        self.append_log("Planning WhatsApp received import directly from the configured source folder.")
        self.append_log("Planning only. No files will be renamed.")
        self.set_safety_status("PLAN ONLY: Building WhatsApp received import plan. No files will be renamed.", "safe")
        for category, folder in options.category_folders.items():
            self.append_log(f"{category.value}: {folder}")
        self.set_progress(0)
        self._start_worker("whatsapp_chrono_plan", whatsapp_chrono_options=options)

    def _whatsapp_sent_category_folders(self) -> dict[WhatsAppSentCategory, Path]:
        return {
            WhatsAppSentCategory.GALLERY_ATTACHMENT: self._resolve_config_path(
                self.config.Gallery_Attachments
            ),
            WhatsAppSentCategory.IN_APP_CAMERA: self._resolve_config_path(
                self.config.In_App_Camera
            ),
            WhatsAppSentCategory.UNCLASSIFIED_OR_CROPPED: self._resolve_config_path(
                self.config.Unclassified_or_Cropped
            ),
        }

    def _whatsapp_received_category_folders(self) -> dict[WhatsAppSentCategory, Path]:
        return {
            WhatsAppSentCategory.RECEIVED: self._resolve_config_path(
                self.config.Received
            ),
        }

    def _whatsapp_category_folders(self) -> dict[WhatsAppSentCategory, Path]:
        return {
            **self._whatsapp_sent_category_folders(),
            **self._whatsapp_received_category_folders(),
        }

    def _resolve_config_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()

    def _build_options(self, dry_run: bool) -> RenameOptions:
        if self.source_folder is None:
            raise RuntimeError("No source folder selected.")

        return self._build_options_for_root(self.source_folder, dry_run=dry_run)

    def _build_options_for_root(self, root: Path, dry_run: bool) -> RenameOptions:
        return RenameOptions(
            root=root,
            name_tz=self.config.name_timezone,
            dry_run=dry_run,
            include_device=self.config.include_device,
            skip_already=True,
            write_manifest=self.write_manifest_check.isChecked(),
            manifest_hash=self.manifest_hash_check.isChecked(),
            show_progress=True,
        )

    def _confirm_process_plan(self) -> bool:
        if self.current_plan is None:
            return False

        manifest_text = (
            "A collection manifest will be written."
            if self.write_manifest_check.isChecked()
            else "No collection manifest will be written."
        )
        response = QMessageBox.question(
            self,
            "Process rename plan?",
            (
                f"Rename {len(self.current_plan.operations)} files according to the reviewed plan?\n\n"
                "ChronoName will verify stale-plan fingerprints before each rename and write an undo journal during processing.\n"
                f"{manifest_text}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

    def _confirm_duplicate_quarantine(self, quarantine_dir: Path) -> bool:
        response = QMessageBox.question(
            self,
            "Quarantine duplicate files?",
            (
                "Move files marked duplicate into the quarantine folder?\n\n"
                f"Destination: {quarantine_dir}\n\n"
                "Create Duplicate Report first if you want to review the duplicate set before moving files."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

    def _confirm_undo_run(self, undo_log_path: Path) -> bool:
        response = QMessageBox.question(
            self,
            "Undo rename run?",
            (
                "Restore filenames from this undo log or journal?\n\n"
                f"{undo_log_path}\n\n"
                "ChronoName will report conflicts instead of overwriting occupied original names."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

    def _start_worker(
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
        if self.worker_thread is not None:
            self.statusBar().showMessage("ChronoName is already working.")
            return

        self.is_busy = True
        self.current_worker_mode = mode
        self._set_busy(True)
        self.statusBar().showMessage("Working...")
        self.worker_thread = QThread(self)
        self.worker = ChronoNameWorker(
            mode=mode,
            options=options,
            plan=plan,
            duplicate_options=duplicate_options,
            filing_audit_options=filing_audit_options,
            whatsapp_root=whatsapp_root,
            whatsapp_process_options=whatsapp_process_options,
            whatsapp_chrono_options=whatsapp_chrono_options,
            undo_log_path=undo_log_path,
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.log.connect(self.append_log)
        self.worker.progress.connect(self.set_progress)
        self.worker.status.connect(self.statusBar().showMessage)
        self.worker.plan_ready.connect(self._handle_plan_ready)
        self.worker.result_ready.connect(self._handle_result_ready)
        self.worker.failed.connect(self._handle_worker_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._worker_finished)
        self.worker_thread.start()

    def _handle_plan_ready(self, plan: RenamePlan) -> None:
        self.current_plan = plan
        self._populate_plan_table(plan)
        self.append_log("")
        self.append_log(f"Metadata entries scanned: {plan.metadata_count}")
        self.append_log(f"Planned renames: {len(plan.operations)}")
        self.append_log(f"Skipped files: {plan.skipped_count}")
        for operation in plan.operations[:20]:
            self.append_log(
                f"{operation.old_path.name} -> "
                f"{operation.new_path.name} ({operation.timestamp_source})"
            )
        if len(plan.operations) > 20:
            self.append_log(f"... and {len(plan.operations) - 20} more")
        self._update_process_action_enabled()
        if plan.operations:
            if self.is_busy:
                self.append_log("Process Rename Plan will be available when planning finishes.")
            else:
                self.append_log("Process Rename Plan is now available from Workflow > Process Rename Plan or Ctrl+Enter.")

    def _handle_result_ready(
        self,
        result: RenameResult | DuplicateResult | CoreDiagnosticsResult | FilingAuditResult | TimestampHealthAuditResult | UndoResult | WhatsAppAnalysisResult | WhatsAppProcessResult | WhatsAppChronoPlanResult,
    ) -> None:
        if isinstance(result, CoreDiagnosticsResult):
            self._handle_core_diagnostics_result(result)
            return
        if isinstance(result, DuplicateResult):
            self._handle_duplicate_result(result)
            return
        if isinstance(result, FilingAuditResult):
            self._handle_filing_audit_result(result)
            return
        if isinstance(result, TimestampHealthAuditResult):
            self._handle_timestamp_health_result(result)
            return
        if isinstance(result, UndoResult):
            self._handle_undo_result(result)
            return
        if isinstance(result, WhatsAppProcessResult):
            self._handle_whatsapp_process_result(result)
            return
        if isinstance(result, WhatsAppChronoPlanResult):
            self._handle_whatsapp_chrono_plan_result(result)
            return
        if isinstance(result, WhatsAppAnalysisResult):
            self._handle_whatsapp_analysis_result(result)
            return

        self.append_log("")
        self.append_log(f"Done. Renamed {result.renamed_count} files.")
        if result.log_path:
            self.append_log(f"Undo log saved to: {result.log_path}")
        if result.journal_path:
            self.append_log(f"Undo journal saved to: {result.journal_path}")
        if result.manifest_path:
            self.append_log(f"Collection manifest saved to: {result.manifest_path}")
        self.current_plan = None
        self.process_action.setEnabled(False)
        self._clear_plan_table()
        if result.skipped:
            self.append_log("Processing failures:")
            for skipped in result.skipped:
                self.append_log(f"[FAIL] {skipped}")
            self.append_log("Build and review a new rename plan before processing again.")
            self.set_safety_status(
                "REPLAN REQUIRED: Some planned renames could not be completed. Build a new plan before processing again.",
                "warning",
            )
            return

        self.set_safety_status(
            f"DONE: Renamed {result.renamed_count} files. Keep the undo log if you may need rollback.",
            "safe",
        )

    def _populate_plan_table(self, plan: RenamePlan) -> None:
        self.plan_table.setSortingEnabled(False)
        self.plan_table.setRowCount(len(plan.operations))
        for row, operation in enumerate(plan.operations):
            size_text = str(operation.source_size) if operation.source_size is not None else ""
            mtime_text = str(operation.source_mtime_ns) if operation.source_mtime_ns is not None else ""
            values = [
                operation.old_path.name,
                operation.new_path.name,
                operation.timestamp_source,
                size_text,
                mtime_text,
                str(operation.old_path.parent),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.plan_table.setItem(row, column, item)
        self.plan_table.setSortingEnabled(True)

    def _clear_plan_table(self) -> None:
        self.plan_table.setRowCount(0)

    def _handle_undo_result(self, result: UndoResult) -> None:
        self.append_log("")
        self.append_log("Undo complete.")
        self.append_log(f"Files restored: {result.undone_count}")
        if result.skipped:
            self.append_log("Undo conflicts or skips:")
            for skipped in result.skipped:
                self.append_log(f"[UNDO] {skipped}")
            self.set_safety_status(
                "UNDO COMPLETE WITH CONFLICTS: Review the log before continuing.",
                "warning",
            )
            return

        self.set_safety_status(
            f"UNDO COMPLETE: Restored {result.undone_count} files.",
            "safe",
        )

    def _handle_duplicate_result(self, result: DuplicateResult) -> None:
        self.append_log("")
        if result.quarantine_dir:
            self.append_log("Duplicate quarantine complete.")
            self.append_log(f"Moved duplicate files to: {result.quarantine_dir}")
            self.set_safety_status(
                f"QUARANTINE COMPLETE: Moved {result.moved_count} duplicate files into .quarantine.",
                "safe",
            )
        else:
            self.append_log("Duplicate report complete.")
            self.append_log("Report only. No files were moved or renamed.")
            self.set_safety_status("REPORT COMPLETE: No files were moved or renamed.", "safe")
        self.append_log(f"Files scanned: {result.files_scanned}")
        self.append_log(f"Duplicate clusters: {result.clusters}")
        self.append_log(f"Files to keep: {result.keep_count}")
        self.append_log(f"Files marked duplicate: {result.drop_count}")
        if result.quarantine_dir:
            self.append_log(f"Files moved to quarantine: {result.moved_count}")
            self.append_log(f"Files that could not be moved: {result.failed_count}")
        if result.csv_path:
            self.append_log(f"CSV report saved to: {result.csv_path}")
        if result.html_path:
            self.append_log(f"HTML report saved to: {result.html_path}")
        elif result.clusters == 0:
            self.append_log("No duplicate clusters found; HTML report was not created.")

    def _handle_core_diagnostics_result(self, result: CoreDiagnosticsResult) -> None:
        self.append_log("")
        self.append_log(result.to_text())
        failed_environment = [item for item in result.environment if not item.ok]
        if result.failed_count or failed_environment:
            self.set_safety_status("DIAGNOSTICS FAILED: Review the report before continuing.", "warning")
            QMessageBox.warning(
                self,
                "ChronoName Core Diagnostics",
                f"{result.passed_count}/{result.total_count} self-tests passed.\nEnvironment checks failed: {len(failed_environment)}",
            )
            return

        self.set_safety_status("DIAGNOSTICS PASSED: Environment checks and core self-tests passed.", "safe")
        QMessageBox.information(
            self,
            "ChronoName Core Diagnostics",
            f"All environment checks passed.\n{result.passed_count}/{result.total_count} self-tests passed.",
        )

    def _handle_filing_audit_result(self, result: FilingAuditResult) -> None:
        self.append_log("")
        self.append_log("Filing audit complete.")
        self.append_log("Report only. No files were moved or renamed.")
        self.set_safety_status("REPORT COMPLETE: Filing audit finished. No files were moved or renamed.", "safe")
        self.append_log(f"Folder: {result.root}")
        self.append_log(f"Mode: {result.mode}")
        self.append_log(f"Files scanned: {result.scanned_count}")
        self.append_log(f"Supported media files: {result.supported_count}")
        self.append_log(f"File findings: {result.anomaly_count}")
        self.append_log(f"Not ChronoName formatted: {result.not_chrononame_count}")
        self.append_log(f"Folder findings: {result.folder_anomaly_count}")
        if result.csv_path:
            self.append_log(f"CSV audit saved to: {result.csv_path}")
        if result.folder_csv_path:
            self.append_log(f"Folder anomaly CSV saved to: {result.folder_csv_path}")
        for item in result.items[:20]:
            self.append_log(
                f"{item.reason}: {item.file_path} "
                f"date={item.file_date or 'n/a'} allowed={item.allowed_range or 'n/a'}"
            )
        if len(result.items) > 20:
            self.append_log(f"... and {len(result.items) - 20} more file findings")

    def _handle_timestamp_health_result(self, result: TimestampHealthAuditResult) -> None:
        self.append_log("")
        self.append_log("Timestamp health audit complete.")
        self.append_log("Audit only. No files were changed.")
        self.set_safety_status("AUDIT COMPLETE: No files were changed.", "safe")
        self.append_log(f"Folder: {result.root}")
        self.append_log(f"Metadata entries scanned: {result.scanned_count}")
        self.append_log(f"Supported media files: {result.supported_count}")
        self.append_log(f"Ready to plan: {result.ready_count}")
        self.append_log(f"Needs review: {result.review_count}")
        self.append_log(f"Skipped: {result.skipped_count}")
        if result.csv_path:
            self.append_log(f"CSV audit saved to: {result.csv_path}")

        self.append_log("")
        self.append_log("Confidence:")
        for confidence, count in sorted(result.confidence_counts.items()):
            self.append_log(f"  {confidence}: {count}")

        self.append_log("Timestamp sources:")
        for source, count in sorted(result.source_counts.items()):
            self.append_log(f"  {source}: {count}")

        if result.warning_counts:
            self.append_log("Warnings:")
            for warning, count in sorted(
                result.warning_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:12]:
                self.append_log(f"  {warning}: {count}")

        review_items = [item for item in result.items if item.warning][:20]
        if review_items:
            self.append_log("")
            self.append_log("Sample review items:")
            for item in review_items:
                chosen = item.chosen_datetime.isoformat() if item.chosen_datetime else "unknown"
                self.append_log(
                    f"{item.filename}: {item.confidence}, {item.timestamp_source}, "
                    f"{chosen}, {item.warning}"
                )

    def _handle_whatsapp_analysis_result(self, result: WhatsAppAnalysisResult) -> None:
        media_kind = (
            "received"
            if result.signatures
            and all(signature.category == WhatsAppSentCategory.RECEIVED for signature in result.signatures)
            else "sent"
        )
        self.append_log("")
        self.append_log(f"WhatsApp {media_kind} analysis complete.")
        self.set_safety_status("ANALYSIS COMPLETE: No files were changed.", "safe")
        self.append_log(f"Folder: {result.root}")
        self.append_log(f"Images scanned: {result.scanned_count}")
        self.append_log(f"Errors: {result.error_count}")
        counts = result.category_counts()
        for category, count in counts.items():
            self.append_log(f"{category.value}: {count}")
        self.append_log("")
        self.append_log("Sample signatures:")
        for signature in result.signatures[:20]:
            self.append_log(
                f"{signature.path.name}: "
                f"{signature.width}x{signature.height}, "
                f"ratio {signature.aspect_ratio:.3f}, "
                f"exif={signature.has_exif}, "
                f"{signature.category.value}"
            )

    def _handle_whatsapp_process_result(self, result: WhatsAppProcessResult) -> None:
        media_kind = (
            "received"
            if WhatsAppSentCategory.RECEIVED in result.target_folders
            else "sent"
        )
        self.append_log("")
        self.append_log(f"WhatsApp {media_kind} preparation complete.")
        self.set_safety_status("COPY PREPARATION COMPLETE: Originals were left in place.", "safe")
        self.append_log(f"Source folder: {result.analysis.root}")
        self.append_log(f"Images scanned: {result.analysis.scanned_count}")
        self.append_log(f"Files copied: {result.copied_count}")
        self.append_log(f"Already present, skipped: {result.skipped_existing_count}")
        self.append_log(f"Errors: {result.error_count}")
        counts = result.analysis.category_counts()
        for category, target in result.target_folders.items():
            count = counts.get(category, 0)
            self.append_log(
                f"{category.value}: {count} -> {target}"
            )

    def _handle_whatsapp_chrono_plan_result(self, result: WhatsAppChronoPlanResult) -> None:
        rename_plan = build_rename_plan_from_whatsapp_chrono_result(
            result,
            name_tz=self.config.name_timezone,
        )
        self.current_plan = rename_plan
        self._populate_plan_table(rename_plan)
        self.append_log("")
        self.append_log("WhatsApp import plan complete.")
        self.append_log("Plan only. No files were renamed.")
        self.set_safety_status("PLAN COMPLETE: Review the plan before processing. No files were renamed.", "safe")
        self.append_log(f"Files planned: {len(result.items)}")
        self.append_log(f"Planned renames: {len(rename_plan.operations)}")
        self.append_log(f"Skipped for rename: {rename_plan.skipped_count}")
        self.append_log("Actions:")
        for action, count in result.action_counts().items():
            self.append_log(f"  {action.value}: {count}")
        self.append_log("Date confidence:")
        for confidence, count in result.confidence_counts().items():
            self.append_log(f"  {confidence.value}: {count}")
        if result.report_path:
            self.append_log(f"CSV plan saved to: {result.report_path}")
        self.append_log("")
        self.append_log("Sample plan items:")
        for item in result.items[:20]:
            chosen = item.chosen_datetime.isoformat() if item.chosen_datetime else "unknown"
            self.append_log(
                f"{item.path.name}: {item.category.value}, "
                f"{item.action.value}, {chosen}, {item.confidence.value}"
            )
        self._update_process_action_enabled()
        if rename_plan.operations:
            self.append_log("")
            if self.is_busy:
                self.append_log("Process Rename Plan will be available when planning finishes.")
            else:
                self.append_log("Process Rename Plan is now available from Workflow > Process Rename Plan or Ctrl+Enter.")

    def _handle_worker_failed(self, message: str) -> None:
        self.append_log("")
        if message == "Operation cancelled.":
            self.append_log("CANCELLED: Operation stopped by request.")
            self.set_safety_status("CANCELLED: Operation stopped by request. Review the log before continuing.", "warning")
            self.statusBar().showMessage("Operation cancelled.")
            return

        self.append_log(f"ERROR: {message}")
        self.set_safety_status("ERROR: Operation stopped before completion. Review the log before continuing.", "danger")
        self.statusBar().showMessage("Operation failed.")

    def _worker_finished(self) -> None:
        completed_mode = self.current_worker_mode
        self.is_busy = False
        self.current_worker_mode = None
        self.worker_thread = None
        self.worker = None
        self._set_busy(False)
        if completed_mode == "whatsapp_process":
            self.statusBar().showMessage("WhatsApp sent preparation complete.")

    def _set_busy(self, busy: bool) -> None:
        self.analyze_action.setEnabled(
            not busy and self.source_folder is not None
        )
        self.health_audit_action.setEnabled(
            not busy and self.source_folder is not None
        )
        self.duplicate_report_action.setEnabled(
            not busy and self.source_folder is not None
        )
        self.filing_audit_action.setEnabled(
            not busy
        )
        self.core_diagnostics_action.setEnabled(
            not busy
        )
        self.duplicate_quarantine_action.setEnabled(
            not busy and self.source_folder is not None
        )
        self.cancel_action.setEnabled(busy)
        self.undo_action.setEnabled(not busy)
        self.whatsapp_sent_action.setEnabled(
            not busy and self.source_folder is not None
        )
        self.whatsapp_received_action.setEnabled(
            not busy and self.source_folder is not None
        )
        self._update_configured_whatsapp_actions(busy=busy)
        self._update_process_action_enabled(busy)

    def _update_process_action_enabled(self, busy: bool | None = None) -> None:
        if busy is None:
            busy = self.is_busy
        self.process_action.setEnabled(
            not busy
            and self.current_plan is not None
            and bool(self.current_plan.operations)
        )

    def _update_configured_whatsapp_actions(self, busy: bool | None = None) -> None:
        if busy is None:
            busy = self.is_busy
        sent_source = self._resolve_config_path(self.config.whatsapp_sent_folder)
        sent_categories = self._whatsapp_sent_category_folders()
        received_source = self._resolve_config_path(self.config.whatsapp_received_folder)
        self.whatsapp_process_action.setEnabled(
            not busy and sent_source.exists() and sent_source.is_dir()
        )
        self.whatsapp_chrono_plan_action.setEnabled(
            not busy
            and any(folder.exists() and folder.is_dir() for folder in sent_categories.values())
        )
        self.whatsapp_received_plan_action.setEnabled(
            not busy and received_source.exists() and received_source.is_dir()
        )

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def set_progress(self, value: int) -> None:
        if value < 0:
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText("...")
            return

        if self.progress_bar.minimum() != 0 or self.progress_bar.maximum() != 100:
            self.progress_bar.setRange(0, 100)
        value = max(0, min(100, value))
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"{value}%")

    def set_safety_status(self, message: str, level: str = "safe") -> None:
        colors = {
            "safe": ("#eef8ee", "#9ac79a", "#1f4d1f"),
            "warning": ("#fff7e6", "#e3b34b", "#6b4700"),
            "danger": ("#fff0f0", "#db8b8b", "#7a1f1f"),
        }
        background, border, text = colors.get(level, colors["safe"])
        self.safety_label.setText(message)
        self.safety_label.setStyleSheet(
            f"""
            QLabel#safetyLabel {{
                border: 1px solid {border};
                background: {background};
                color: {text};
                padding: 5px 8px;
                font-weight: 600;
            }}
            """
        )

    # cleanup when closing
    def closeEvent(self, event):
        if self.worker_thread is not None:
            response = QMessageBox.question(
                self,
                "Operation still running",
                (
                    "ChronoName is still working.\n\n"
                    "Request cancellation and keep the window open until the operation stops?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if response == QMessageBox.StandardButton.Yes:
                self._cancel_current_operation()
            event.ignore()
            return

        print("[Main] Closing App")
        super().closeEvent(event)        

