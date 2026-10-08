"""Consumer checks use only generated media in disposable directories."""
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from duplicate_core import run_duplicate_detection
from models import DuplicateOptions
from workers import ChronoNameWorker


class DuplicateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = self.root / "a.png"
        image = Image.new("RGB", (128, 128))
        image.putdata([((x * 17 + y * 13) % 256, (x * y) % 256,
                        (x * 3 + y * 29) % 256) for y in range(128) for x in range(128)])
        image.save(self.a)
        self.b = self.root / "nested" / "b.png"
        self.b.parent.mkdir()
        shutil.copyfile(self.a, self.b)

    def options(self, **kwargs):
        return DuplicateOptions(roots=[self.root], max_workers=2, **kwargs)

    def test_report_only_exact_and_perceptual(self):
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in (self.a, self.b)}
        for exact in (False, True):
            result = run_duplicate_detection(self.options(do_exact_hash=exact))
            self.assertEqual((result.files_scanned, result.clusters, result.keep_count,
                              result.drop_count), (2, 1, 1, 1))
            self.assertTrue(result.csv_path.is_file())
            self.assertTrue(result.html_path.is_file())
            self.assertEqual(result.moved_count, 0)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).digest() for p in before})

    def test_exclusions_custom_paths_and_outputs(self):
        excluded = self.root / "custom-exclude"
        quarantine = self.root / "custom-quarantine"
        for folder in (excluded, quarantine, self.root / ".quarantine",
                       self.root / "ChronoName Reports"):
            folder.mkdir(exist_ok=True)
            shutil.copyfile(self.a, folder / "ignored.png")
        result = run_duplicate_detection(self.options(exclude_dirs=[excluded], quarantine_dir=quarantine))
        self.assertEqual(result.files_scanned, 2)

    def test_quarantine_collision_progress_and_rescan(self):
        quarantine = self.root / ".quarantine"
        # Fill both possible destinations so keeper tie-breaking is irrelevant.
        for relative in (Path("a.png"), Path("nested/b.png")):
            target = quarantine / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"existing quarantine content")
        events = []
        result = run_duplicate_detection(self.options(quarantine_duplicates=True, dry_run=False,
                     quarantine_dir=quarantine, progress_callback=lambda *event: events.append(event)))
        self.assertEqual((result.moved_count, result.failed_count), (1, 0))
        self.assertEqual(sum(p.exists() for p in (self.a, self.b)), 1)
        self.assertEqual(len(list(quarantine.rglob("*__dup1.png"))), 1)
        self.assertEqual((quarantine / "a.png").read_bytes(), b"existing quarantine content")
        self.assertTrue(all(0 <= done <= total for _, done, total, _ in events))
        self.assertEqual(run_duplicate_detection(self.options()).files_scanned, 1)

    def test_dry_run(self):
        result = run_duplicate_detection(self.options(quarantine_duplicates=True,
                      quarantine_dir=self.root / ".quarantine"))
        self.assertEqual(result.moved_count, 0)
        self.assertTrue(self.a.exists() and self.b.exists())

    def test_action_failure_visible(self):
        logs = []
        with patch("hdw_dedup_engine.actions.shutil.move", side_effect=PermissionError("test denied")):
            result = run_duplicate_detection(self.options(quarantine_duplicates=True, dry_run=False,
                      quarantine_dir=self.root / ".quarantine", log_callback=logs.append))
        self.assertEqual((result.moved_count, result.failed_count), (0, 1))
        self.assertTrue(any("test denied" in line for line in logs))

    def test_worker_result_and_cancel_signals(self):
        worker = ChronoNameWorker("duplicates", duplicate_options=self.options())
        results, errors, finished, progress = [], [], [], []
        worker.result_ready.connect(results.append)
        worker.failed.connect(errors.append)
        worker.finished.connect(lambda: finished.append(True))
        worker.progress.connect(progress.append)
        worker.run()
        self.assertEqual(len(results), 1)
        self.assertEqual(errors, [])
        self.assertEqual(finished, [True])
        self.assertTrue(all(0 <= value <= 100 for value in progress))
        worker = ChronoNameWorker("duplicates", duplicate_options=self.options())
        worker.failed.connect(errors.append)
        worker.cancel()
        worker.run()
        self.assertIn("cancel", errors[-1].lower())

    def test_cancellation_during_hashing(self):
        cancelled = False
        def progress(*event):
            nonlocal cancelled
            cancelled = True
        with self.assertRaisesRegex(RuntimeError, "[Cc]ancel"):
            run_duplicate_detection(self.options(cancel_callback=lambda: cancelled,
                                                 progress_callback=progress))


if __name__ == "__main__":
    unittest.main()
