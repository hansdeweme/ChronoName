from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from config import _resource_path
from exiftool_adapter import _exiftool_bin
from version import VERSION


@dataclass
class DiagnosticLine:
    label: str
    value: str
    ok: bool = True
    details: str = ""


@dataclass
class CoreDiagnosticsResult:
    version: str
    frozen: bool
    environment: list[DiagnosticLine] = field(default_factory=list)
    self_tests: list[DiagnosticLine] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for item in self.self_tests if item.ok)

    @property
    def total_count(self) -> int:
        return len(self.self_tests)

    @property
    def failed_count(self) -> int:
        return self.total_count - self.passed_count

    def to_text(self) -> str:
        lines = [
            "ChronoName Core Diagnostics",
            f"Version: {self.version}",
            f"Frozen executable: {'Yes' if self.frozen else 'No'}",
            "",
            "Environment",
        ]
        for item in self.environment:
            status = "PASS" if item.ok else "FAIL"
            lines.append(f"{item.label:<32} {status}  {item.value}")
            if item.details:
                lines.append(f"  {item.details}")

        lines.extend(["", "Self-tests"])
        for item in self.self_tests:
            status = "PASS" if item.ok else "FAIL"
            lines.append(f"{item.label:.<32} {status}")
            if item.details:
                lines.append(f"  {item.details}")

        lines.extend(["", f"{self.passed_count}/{self.total_count} tests passed"])
        return "\n".join(lines)


def run_core_diagnostics() -> CoreDiagnosticsResult:
    result = CoreDiagnosticsResult(
        version=VERSION,
        frozen=bool(getattr(sys, "frozen", False)),
    )
    result.environment.extend(_environment_checks())
    result.self_tests.extend(_self_test_checks())
    return result


def _application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _environment_checks() -> list[DiagnosticLine]:
    checks = [
        DiagnosticLine("ChronoName version", VERSION),
        DiagnosticLine(
            "Frozen / source",
            "Frozen executable" if getattr(sys, "frozen", False) else "Source checkout",
        ),
        DiagnosticLine("Python runtime", sys.version.split()[0]),
        DiagnosticLine("Application directory", str(_application_dir())),
        _resource_exists_check("settings.json found", "settings.json"),
        _exiftool_check(),
        _import_check("DedupTool import/version", "deduptool"),
        _import_check("Pillow available", "PIL.Image"),
        _heic_check(),
    ]
    return checks


def _resource_exists_check(label: str, filename: str) -> DiagnosticLine:
    path = _resource_path(filename)
    return DiagnosticLine(label, str(path), path.exists())


def _exiftool_check() -> DiagnosticLine:
    executable = _exiftool_bin()
    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        completed = subprocess.run(
            [executable, "-ver"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=True,
            **kwargs,
        )
        version = (completed.stdout or "").strip() or "version unknown"
        return DiagnosticLine("ExifTool found + version", f"{executable} ({version})")
    except Exception as exc:
        return DiagnosticLine("ExifTool found + version", executable, False, str(exc))


def _import_check(label: str, module_name: str) -> DiagnosticLine:
    try:
        module = importlib.import_module(module_name)
        root_module = importlib.import_module(module_name.split(".", 1)[0])
        version = getattr(root_module, "__version__", "") or getattr(module, "__version__", "")
        value = f"{module_name} {version}".strip()
        return DiagnosticLine(label, value)
    except Exception as exc:
        return DiagnosticLine(label, module_name, False, str(exc))


def _heic_check() -> DiagnosticLine:
    try:
        pillow_heif = importlib.import_module("pillow_heif")
        if hasattr(pillow_heif, "register_heif_opener"):
            pillow_heif.register_heif_opener()
        version = getattr(pillow_heif, "__version__", "")
        value = f"pillow_heif {version}".strip()
        return DiagnosticLine("HEIC decoding capability", value)
    except Exception as exc:
        return DiagnosticLine("HEIC decoding capability", "pillow_heif", False, str(exc))


def _self_test_checks() -> list[DiagnosticLine]:
    try:
        import test_chrononame_core as tests
    except Exception as exc:
        details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return [
            DiagnosticLine(label, "", False, details)
            for label, _ in _TEST_GROUPS
        ]

    temp_parent = _diagnostics_temp_parent()
    original_temporary_directory = getattr(tests, "TemporaryDirectory", None)
    tests.TemporaryDirectory = lambda **kwargs: _DiagnosticTemporaryDirectory(
        kwargs.pop("dir", temp_parent)
    )

    checks = []
    try:
        for label, cases in _TEST_GROUPS:
            suite = unittest.TestSuite()
            for class_name, method_name in cases:
                suite.addTest(getattr(tests, class_name)(method_name))
            test_result = unittest.TestResult()
            suite.run(test_result)
            details = _format_test_details(test_result)
            checks.append(DiagnosticLine(label, "", test_result.wasSuccessful(), details))
    finally:
        if original_temporary_directory is not None:
            tests.TemporaryDirectory = original_temporary_directory
        try:
            temp_parent.rmdir()
        except OSError:
            pass
    return checks


def _diagnostics_temp_parent() -> Path:
    candidates = [
        Path.cwd() / ".chrononame_diagnostics_tmp",
        _application_dir() / ".chrononame_diagnostics_tmp",
        Path(tempfile.gettempdir()) / "ChronoName Diagnostics",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise RuntimeError("No writable temporary directory is available for diagnostics.")


class _DiagnosticTemporaryDirectory:
    def __init__(self, parent: Path) -> None:
        self.name = str(parent / f"diagnostic_{uuid.uuid4().hex}")

    def __enter__(self) -> str:
        Path(self.name).mkdir(parents=True, exist_ok=False)
        return self.name

    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        shutil.rmtree(self.name, ignore_errors=True)


def _format_test_details(result: unittest.TestResult) -> str:
    messages = []
    for test, err in result.failures + result.errors:
        messages.append(f"{test.id()}: {err.splitlines()[-1] if err else 'failed'}")
    return "\n  ".join(messages)


_TEST_GROUPS = [
    (
        "Timestamp decision logic",
        [
            ("ExecuteRenamePlanTests", "test_timestamp_decision_uses_capture_metadata_and_flags_filename_conflict"),
            ("ExecuteRenamePlanTests", "test_timestamp_decision_can_match_filename_date_with_file_modify_time"),
        ],
    ),
    (
        "ChronoName filename parser",
        [("FilingAuditTests", "test_chrononame_filename_parser_supports_existing_normalized_forms")],
    ),
    (
        "Rename destination conflicts",
        [("ExecuteRenamePlanTests", "test_destination_conflict_is_skipped_without_choosing_new_name")],
    ),
    (
        "Stale-plan protection",
        [("ExecuteRenamePlanTests", "test_stale_plan_is_skipped_when_source_file_changed_after_review")],
    ),
    (
        "Undo journal creation",
        [("ExecuteRenamePlanTests", "test_successful_rename_writes_json_log_and_jsonl_journal")],
    ),
    (
        "Partial journal recovery",
        [("ExecuteRenamePlanTests", "test_undo_ignores_partial_jsonl_tail")],
    ),
    (
        "Strict undo conflicts",
        [("ExecuteRenamePlanTests", "test_undo_reports_conflict_when_original_name_is_occupied")],
    ),
    (
        "Filing audit",
        [
            ("FilingAuditTests", "test_correct_chrononame_file_inside_correct_year_folder_has_no_anomaly"),
            ("FilingAuditTests", "test_file_outside_dated_folder_range_is_reported_as_folder_range"),
            ("FilingAuditTests", "test_cross_year_range_beyond_configured_allowance_is_reported"),
        ],
    ),
    (
        "Filing audit read-only check",
        [("FilingAuditTests", "test_audit_writes_reports_without_mutating_source_media_files")],
    ),
    (
        "Dedup scan exclusions",
        [("DuplicateScanSettingsTests", "test_duplicate_scan_settings_exclude_reports_and_quarantine_folders")],
    ),
]
