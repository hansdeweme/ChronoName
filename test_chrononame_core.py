from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from zoneinfo import ZoneInfo

from chrononame_core import (
    evaluate_timestamp_decision,
    execute_rename_plan,
    parse_chrononame_filename,
    parse_filename_datetime,
    undo_renames,
)
from config import load_config
from duplicate_core import QUARANTINE_FOLDER_NAME, build_duplicate_scan_settings
from filing_audit import parse_folder_range_from_name, run_filing_audit
from models import FilingAuditOptions, RenameOperation, RenameOptions, RenamePlan
from models import DuplicateOptions


class ExecuteRenamePlanTests(unittest.TestCase):
    def test_timestamp_decision_uses_capture_metadata_and_flags_filename_conflict(self) -> None:
        meta = {
            "SourceFile": "IMG-20260805-WA0001.jpg",
            "DateTimeOriginal": "2026:08:04 12:30:00",
            "FileModifyDate": "2026:08:05 14:30:00",
        }

        decision = evaluate_timestamp_decision(
            meta,
            path=Path("IMG-20260805-WA0001.jpg"),
            name_tz=ZoneInfo("Europe/Amsterdam"),
        )

        self.assertEqual(decision.chosen_datetime.isoformat(), "2026-08-04T12:30:00")
        self.assertEqual(decision.source, "DateTimeOriginal")
        self.assertEqual(decision.confidence, "high_embedded_metadata")
        self.assertIn("metadata_filename_date_conflict", decision.warnings)

    def test_timestamp_decision_can_match_filename_date_with_file_modify_time(self) -> None:
        meta = {
            "SourceFile": "IMG-20260805-WA0001.jpg",
            "FileModifyDate": "2026:08:05 14:30:00",
        }

        decision = evaluate_timestamp_decision(
            meta,
            path=Path("IMG-20260805-WA0001.jpg"),
            name_tz=ZoneInfo("Europe/Amsterdam"),
        )

        self.assertEqual(decision.chosen_datetime.isoformat(), "2026-08-05T14:30:00")
        self.assertEqual(decision.source, "filename_date+filemodify_time_same_day")
        self.assertEqual(decision.confidence, "medium_tentative_time")

    def test_destination_conflict_is_skipped_without_choosing_new_name(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.jpg"
            dst = root / "20260805_120000.jpg"
            alternate_dst = root / "20260805_120000_002.jpg"
            log_path = root / "rename_log.json"

            src.write_text("source", encoding="utf-8")
            dst.write_text("existing", encoding="utf-8")

            plan = RenamePlan(
                root=root,
                operations=[
                    RenameOperation(
                        old_path=src,
                        new_path=dst,
                        timestamp_source="DateTimeOriginal",
                    )
                ],
                manifest_entries=[],
                metadata_count=1,
                skipped_count=0,
                name_tz="Europe/Amsterdam",
            )
            options = RenameOptions(root=root, dry_run=False, log_path=log_path, show_progress=False)

            result = execute_rename_plan(plan, options)

            self.assertEqual(result.renamed_count, 0)
            self.assertEqual(result.operations, [])
            self.assertEqual(len(result.skipped), 1)
            self.assertIn("Conflict: planned destination is no longer available", result.skipped[0])
            self.assertTrue(src.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), "existing")
            self.assertFalse(alternate_dst.exists())

    def test_stale_plan_is_skipped_when_source_file_changed_after_review(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.jpg"
            dst = root / "20260805_120000.jpg"
            log_path = root / "rename_log.json"

            src.write_text("planned content", encoding="utf-8")
            source_stat = src.stat()
            plan = RenamePlan(
                root=root,
                operations=[
                    RenameOperation(
                        old_path=src,
                        new_path=dst,
                        timestamp_source="DateTimeOriginal",
                        source_size=source_stat.st_size,
                        source_mtime_ns=source_stat.st_mtime_ns,
                    )
                ],
                manifest_entries=[],
                metadata_count=1,
                skipped_count=0,
                name_tz="Europe/Amsterdam",
            )
            src.write_text("changed content with a different size", encoding="utf-8")
            options = RenameOptions(root=root, dry_run=False, log_path=log_path, show_progress=False)

            result = execute_rename_plan(plan, options)

            self.assertEqual(result.renamed_count, 0)
            self.assertEqual(result.operations, [])
            self.assertEqual(
                result.skipped,
                [
                    "STALE PLAN: file changed after review\n"
                    f"file: {src}"
                ],
            )
            self.assertTrue(src.exists())
            self.assertFalse(dst.exists())

    def test_execute_rename_plan_stops_when_cancelled(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.jpg"
            dst = root / "20260805_120000.jpg"
            log_path = root / "rename_log.json"

            src.write_text("source", encoding="utf-8")
            source_stat = src.stat()
            plan = RenamePlan(
                root=root,
                operations=[
                    RenameOperation(
                        old_path=src,
                        new_path=dst,
                        timestamp_source="DateTimeOriginal",
                        source_size=source_stat.st_size,
                        source_mtime_ns=source_stat.st_mtime_ns,
                    )
                ],
                manifest_entries=[],
                metadata_count=1,
                skipped_count=0,
                name_tz="Europe/Amsterdam",
            )
            options = RenameOptions(
                root=root,
                dry_run=False,
                log_path=log_path,
                show_progress=False,
                cancel_callback=lambda: True,
            )

            with self.assertRaisesRegex(RuntimeError, "Operation cancelled."):
                execute_rename_plan(plan, options)

            self.assertTrue(src.exists())
            self.assertFalse(dst.exists())

    def test_successful_rename_writes_json_log_and_jsonl_journal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.jpg"
            dst = root / "20260805_120000.jpg"
            log_path = root / "rename_log.json"
            journal_path = root / "rename_log.jsonl"

            src.write_text("source", encoding="utf-8")
            plan = RenamePlan(
                root=root,
                operations=[
                    RenameOperation(
                        old_path=src,
                        new_path=dst,
                        timestamp_source="DateTimeOriginal",
                    )
                ],
                manifest_entries=[],
                metadata_count=1,
                skipped_count=0,
                name_tz="Europe/Amsterdam",
            )
            options = RenameOptions(root=root, dry_run=False, log_path=log_path, show_progress=False)

            result = execute_rename_plan(plan, options)

            self.assertEqual(result.renamed_count, 1)
            self.assertEqual(result.skipped, [])
            self.assertEqual(result.log_path, log_path)
            self.assertEqual(result.journal_path, journal_path)
            self.assertTrue(log_path.exists())
            self.assertTrue(journal_path.exists())
            journal_entries = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertEqual(journal_entries, [result.operations[0].to_log_entry()])

    def test_undo_can_read_jsonl_journal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.jpg"
            dst = root / "20260805_120000.jpg"
            log_path = root / "rename_log.json"
            journal_path = root / "rename_log.jsonl"

            src.write_text("source", encoding="utf-8")
            plan = RenamePlan(
                root=root,
                operations=[
                    RenameOperation(
                        old_path=src,
                        new_path=dst,
                        timestamp_source="DateTimeOriginal",
                    )
                ],
                manifest_entries=[],
                metadata_count=1,
                skipped_count=0,
                name_tz="Europe/Amsterdam",
            )
            options = RenameOptions(root=root, dry_run=False, log_path=log_path, show_progress=False)

            execute_rename_plan(plan, options)
            result = undo_renames(journal_path)

            self.assertEqual(result.undone_count, 1)
            self.assertEqual(result.skipped, [])
            self.assertTrue(src.exists())
            self.assertFalse(dst.exists())

    def test_undo_ignores_partial_jsonl_tail(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.jpg"
            dst = root / "20260805_120000.jpg"
            journal_path = root / "rename_log.jsonl"

            dst.write_text("renamed", encoding="utf-8")
            entry = RenameOperation(
                old_path=src,
                new_path=dst,
                timestamp_source="DateTimeOriginal",
            ).to_log_entry()
            journal_path.write_text(
                json.dumps(entry) + "\n" + '{"old": ',
                encoding="utf-8",
            )

            result = undo_renames(journal_path)

            self.assertEqual(result.undone_count, 1)
            self.assertEqual(result.skipped, [])
            self.assertTrue(src.exists())
            self.assertFalse(dst.exists())

    def test_undo_reports_conflict_when_original_name_is_occupied(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "IMG_1234.jpg"
            dst = root / "20260805_120000.jpg"
            alternate_dst = root / "IMG_1234_002.jpg"
            journal_path = root / "rename_log.jsonl"

            src.write_text("new occupant", encoding="utf-8")
            dst.write_text("renamed original", encoding="utf-8")
            entry = RenameOperation(
                old_path=src,
                new_path=dst,
                timestamp_source="DateTimeOriginal",
            ).to_log_entry()
            journal_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

            result = undo_renames(journal_path)

            self.assertEqual(result.undone_count, 0)
            self.assertEqual(
                result.skipped,
                [
                    "UNDO CONFLICT:\n"
                    "wanted: IMG_1234.jpg\n"
                    "reason: destination already exists"
                ],
            )
            self.assertEqual(src.read_text(encoding="utf-8"), "new occupant")
            self.assertEqual(dst.read_text(encoding="utf-8"), "renamed original")
            self.assertFalse(alternate_dst.exists())


class FilingAuditTests(unittest.TestCase):
    def _write_media(self, path: Path, content: str = "media") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _run(self, root: Path, *, tolerance_days: int = 1, cross_year_forward_days: int = 14):
        return run_filing_audit(
            FilingAuditOptions(
                root=root,
                tolerance_days=tolerance_days,
                cross_year_forward_days=cross_year_forward_days,
                ignored_folder_names=["edits", "exports", "scans"],
                show_progress=False,
            )
        )

    def test_correct_chrononame_file_inside_correct_year_folder_has_no_anomaly(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            self._write_media(root / "20240724_153211.jpg")

            result = self._run(root)

            self.assertEqual(result.mode, "year_root")
            self.assertEqual(result.anomaly_count, 0)

    def test_chrononame_file_for_another_year_inside_year_root_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            self._write_media(root / "20250103_153211.jpg")

            result = self._run(root)

            self.assertEqual([item.reason for item in result.items], ["FileDateOutsideSelectedYearFolder"])
            self.assertEqual(result.items[0].allowed_range, "2023-12-31..2025-01-01")
            self.assertEqual(result.items[0].checked_against, str(root))

    def test_correct_filename_inside_dated_range_folder_has_no_anomaly(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            self._write_media(root / "20240720_20240728-Liguria" / "20240724_153211.jpg")

            result = self._run(root)

            self.assertEqual(result.anomaly_count, 0)

    def test_file_outside_dated_folder_range_is_reported_as_folder_range(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            folder = root / "20240720_20240728-Liguria"
            self._write_media(folder / "20240812_092201.jpg")

            result = self._run(root)

            self.assertEqual([item.reason for item in result.items], ["FileDateOutsideFolderDateRange"])
            self.assertEqual(result.items[0].checked_against, str(folder))
            self.assertEqual(result.items[0].allowed_range, "2024-07-20..2024-07-28")

    def test_general_root_containing_dated_folder_still_checks_folder_range(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Photos" / "Holidays"
            self._write_media(root / "20240720_20240728-Liguria" / "20240812_092201.jpg")

            result = self._run(root)

            self.assertEqual(result.mode, "general_root")
            self.assertEqual([item.reason for item in result.items], ["FileDateOutsideFolderDateRange"])

    def test_general_root_without_dated_ancestor_does_not_invent_year_constraint(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Photos" / "Holidays"
            self._write_media(root / "misc" / "20250103_153211.jpg")

            result = self._run(root)

            self.assertEqual(result.mode, "general_root")
            self.assertEqual(result.anomaly_count, 0)

    def test_non_chrononame_media_filename_is_reported_neutrally(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            self._write_media(root / "IMG_1234.jpg")

            result = self._run(root)

            self.assertEqual([item.reason for item in result.items], ["NotChronoNameFormatted"])
            self.assertEqual(result.not_chrononame_count, 1)

    def test_single_date_folder_parsing_works(self) -> None:
        parsed = parse_folder_range_from_name("20240720-Beach")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0].isoformat(), "2024-07-20")
        self.assertEqual(parsed[1].isoformat(), "2024-07-20")

    def test_date_range_folder_parsing_works(self) -> None:
        parsed = parse_folder_range_from_name("20240720_20240728-Liguria")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0].isoformat(), "2024-07-20")
        self.assertEqual(parsed[1].isoformat(), "2024-07-28")

    def test_cross_year_range_within_configured_allowance_works(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            self._write_media(root / "20241230_20250110-New-Year" / "20250110_090000.jpg")

            result = self._run(root, cross_year_forward_days=14)

            self.assertEqual(result.anomaly_count, 0)
            self.assertEqual(result.folder_anomaly_count, 0)

    def test_cross_year_range_beyond_configured_allowance_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            self._write_media(root / "20241230_20250120-New-Year" / "20250120_090000.jpg")

            result = self._run(root, cross_year_forward_days=14)

            self.assertEqual([item.reason for item in result.items], ["FileDateOutsideFolderDateRange"])
            self.assertEqual(
                [item.reason for item in result.folder_anomalies],
                ["CrossYearRangeBeyondAllowedForwardSpillover"],
            )

    def test_tolerance_days_is_loaded_from_configuration_and_affects_boundaries(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = tmp_path / "settings.json"
            settings.write_text(
                json.dumps({"filing_audit": {"tolerance_days": 1, "cross_year_forward_days": 14}}),
                encoding="utf-8",
            )
            config = load_config(settings)
            root = tmp_path / "Photos"
            self._write_media(root / "20240720-Event" / "20240721_090000.jpg")

            tolerant = run_filing_audit(
                FilingAuditOptions(
                    root=root,
                    tolerance_days=config.filing_audit.tolerance_days,
                    cross_year_forward_days=config.filing_audit.cross_year_forward_days,
                    show_progress=False,
                )
            )
            strict = self._run(root, tolerance_days=0)

            self.assertEqual(tolerant.anomaly_count, 0)
            self.assertEqual([item.reason for item in strict.items], ["FileDateOutsideFolderDateRange"])

    def test_cross_year_forward_days_is_loaded_from_configuration(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = tmp_path / "settings.json"
            settings.write_text(
                json.dumps({"filing_audit": {"tolerance_days": 0, "cross_year_forward_days": 20}}),
                encoding="utf-8",
            )
            config = load_config(settings)
            root = tmp_path / "2024"
            self._write_media(root / "20241230_20250116-New-Year" / "20250116_090000.jpg")

            result = run_filing_audit(
                FilingAuditOptions(
                    root=root,
                    tolerance_days=config.filing_audit.tolerance_days,
                    cross_year_forward_days=config.filing_audit.cross_year_forward_days,
                    show_progress=False,
                )
            )

            self.assertEqual(result.anomaly_count, 0)

    def test_chrononame_filename_parser_supports_existing_normalized_forms(self) -> None:
        parsed = parse_chrononame_filename("20260805_120000_123__CANON-EOS_002.JPG")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.datetime.isoformat(), "2026-08-05T12:00:00")
        self.assertEqual(parsed.milliseconds, 123)
        self.assertEqual(parsed.device, "CANON-EOS")
        self.assertEqual(parsed.collision_counter, 2)
        self.assertEqual(parsed.extension, ".jpg")
        self.assertEqual(parse_filename_datetime("IMG-20260805-WA0001.jpg").isoformat(), "2026-08-05T00:00:00")
        self.assertEqual(parse_filename_datetime("PXL_20260805_120000.jpg").isoformat(), "2026-08-05T12:00:00")

    def test_audit_writes_reports_without_mutating_source_media_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "2024"
            media = [
                self._write_media(root / "20240720_20240728-Trip" / "20240812_092201.jpg", "a"),
                self._write_media(root / "IMG_1234.jpg", "b"),
            ]
            before = {path.relative_to(root): path.read_text(encoding="utf-8") for path in media}

            result = self._run(root)

            after = {path.relative_to(root): path.read_text(encoding="utf-8") for path in media}
            self.assertEqual(after, before)
            self.assertTrue(result.csv_path.exists())
            self.assertTrue(result.folder_csv_path.exists())
            self.assertEqual(result.csv_path.parent.name, "ChronoName Reports")


class DuplicateScanSettingsTests(unittest.TestCase):
    def test_duplicate_scan_settings_exclude_reports_and_quarantine_folders(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "ChronoName Reports"
            extra_exclude = root / QUARANTINE_FOLDER_NAME

            settings = build_duplicate_scan_settings(
                DuplicateOptions(
                    roots=[root],
                    exclude_dirs=[extra_exclude],
                ),
                report_dir,
            )

            scan = settings["scan"]
            self.assertIn("ChronoName Reports", scan["exclude_dirnames"])
            self.assertIn(QUARANTINE_FOLDER_NAME, scan["exclude_dirnames"])
            self.assertIn(str(report_dir.resolve()), scan["exclude_dirpaths"])
            self.assertIn(str(extra_exclude.resolve()), scan["exclude_dirpaths"])


if __name__ == "__main__":
    unittest.main()

