# ChronoName migration to HdWDedupEngine 0.1.0

## Repository and safety

- Repository: `D:\Coding\ChronoName`, branch `master`.
- Pre-migration commit: `301721f` — Back up recovered ChronoName codebase and bundled dependencies.
- Origin fetch/push: `https://github.com/hansdeweme/ChronoName.git`.
- Initial status: only untracked `clean_pyinstaller.cmd` and `run_pyinstaller.cmd`.
- Original migration-target files and both scripts were copied to
  `C:\Users\hans\AppData\Local\Temp\chrononame-engine-migration\original`
  before editing. The original run script targeted DedupTool's absent entrypoint;
  it was backed up and replaced as required by this task. The clean script is
  unchanged and was never run. Existing dist folders, recovered source ZIP,
  settings, bundled resources, journals, reports and user media were preserved.
- No commit, push, reset, clean or force operation. DedupTool, Person Recognition
  and engine implementation were not modified.

## Dependency inventory

| Location | Classification | Finding/result |
| --- | --- | --- |
| duplicate_core.py | A/C | Public config, engine, settings, CSV/HTML and move functions; imports migrated to package root |
| diagnostics_core.py | A/C/D | Replaced legacy import/version probe with engine version and module path |
| ui.py, workers.py, models.py | C | Application-owned workflow, Qt signals and result dataclasses retained |
| config.py, report_paths.py, settings.json | C/E | Application settings/resource/report ownership retained; no user settings changed |
| requirements.txt, build scripts | A/C/D | Explicit engine version, installed-package collection and corrected ChronoName entrypoint |
| py_sources_to_txt.py | C/D | Removed reference to absent find_duplicates.py; included diagnostics and filing audit |
| test_chrononame_core.py | C | Existing exclusion assertions updated to effective engine schema |
| cache/index | E | No existing IndexDB integration; none introduced |
| historical combined source/recovered ZIP | D/E | Preserved; never imported |

No local deduptool directory, copied active engine, old find_duplicates.py,
active sys.path hack or hard-coded DedupTool runtime path existed. The UI method
`_find_duplicates_report` is an application handler, not an obsolete module.
No direct engine submodule imports were needed in application code. The failure
test patches the public action implementation's filesystem operation solely to
simulate a permission failure; no engine implementation is copied.

## Baseline

ChronoName pytest collection failed with `ModuleNotFoundError: deduptool`.
Built-in diagnostics failed the legacy engine environment check and all ten
self-test groups because their shared test module could not import duplicate_core.
ExifTool 13.37, Pillow and HEIC environment checks already passed. A baseline
duplicate run and GUI could not initialize with the missing dependency.
The engine baseline was **79 passed**, with no skips.

## Integration and path decisions

- Public APIs used: `DedupConfig`, `DedupEngine`, `load_settings`, `write_csv`,
  `write_html`, `execute_moves`. Existing summary/action dictionaries and
  ChronoName result dataclasses remain in use.
- Engine cancellation callback is now supplied directly as well as checked at
  application progress/report/action boundaries.
- Engine action progress is a percentage; it is adapted to ChronoName's
  `(stage, done, total, message)` callback using `total=100`. Previously the
  percentage was divided by the number of drop files, producing invalid GUI progress.
- Explicit directory exclusions now use the engine's `exclude_roots`; the old
  `exclude_dirpaths` key was ineffective. Existing legacy settings entries are
  retained and folded into the effective exclusion list. Reports, conventional
  `.quarantine`, explicit quarantine and user exclusion directories are excluded.
- The report base directory is absolute and Windows normcase-normalized to
  avoid the inherited report-root exclusion caveat. CSV, HTML and generated
  assets remain under `<configured report parent>\ChronoName Reports`.
- A configured thumbnail cache is anchored below that report directory. No
  database is introduced. No output is directed into the installed engine.
- Existing settings loading is retained: the engine still selects its settings
  using cwd/source or executable/frozen behavior and ignores its path argument.
  This limitation was not redesigned. ChronoName overrides only its owned
  output/exclusion paths.
- Engine matching thresholds, aspect guard, corroboration, HEIC relaxation,
  SSIM, keeper ranking, hashing and clustering were unchanged.

## Verification results

- ChronoName pytest: **32 passed** (25 existing tests plus 7 focused integration tests).
- Unittest discovery: **32 tests, OK**.
- Source built-in diagnostics: **10/10 groups**, all nine environment checks pass.
- Source offscreen QApplication/MainWindow startup: visible window, no import errors.
- Engine final gate: **79 passed**, no skips; optional source SSIM test passed.
- Generated-file WhatsApp sent/received analysis and ExifTool dimension reading
  passed without changing the generated JPEG.
- Existing regressions cover timestamp decisions, parser, rename conflicts,
  stale plan checks, undo journals, partial journal recovery, strict undo
  conflicts and report-only filing audit. Their implementations were untouched.
- Git diff whitespace check passes. Git emits ordinary LF/CRLF conversion notices.

The seven integration tests verify real scans of generated textured PNGs with
exact hashing both enabled and disabled; expected 2 files/1 cluster/1 keeper/1
drop; real CSV/HTML files; unchanged source contents; conventional and custom
output/exclusion paths; actual quarantine moves; preserved relative folder
structure; `__dup1` collision handling without overwrites; keeper survival;
rescan excluding output; dry-run preservation; permission failure counts/logs;
worker result/error/finished signals; bounded progress; cancellation before
work and during hashing. All filesystem actions use disposable generated files.

## PyInstaller and frozen checks

The backed-up run script now invokes `build_chrononame.py`. It builds the actual
main.py as a windowed onedir ChronoName executable, collects installed
hdw_dedup_engine, pillow_heif and send2trash, preserves PyQt6 hooks and excludes
optional skimage/SciPy. OpenCV is not required. Settings and icon are bundled;
the generated spec is kept in ignored build/. Extra PyInstaller arguments are supported.

A frozen verification run exposed an ExifTool issue: automatic binary dependency
collection duplicated perl532.dll beside the launcher and broke Perl's relative
library lookup (`strict.pm` missing). The build helper now copies ExifTool and
its original portable directory after collection, preserving the external tool
without altering application subprocess code. Contents remain executable-relative.
CREATE_NO_WINDOW handling is unchanged. No interactive console-flash observation
is claimed from offscreen automation.

The verification build at `dist\engine-migration\ChronoName\ChronoName.exe`
uses an external, inert-unless-requested runtime hook. That executable actually
created the GUI, ran frozen diagnostics and drove all seven integration tests
against generated disposable media through the application's core and Qt worker.
Results: GUI visible, engine 0.1.0 resolved inside the frozen distribution,
ExifTool 13.37, all environment checks, **10/10 diagnostics**, **7 integration
tests**, no failures. This is executable-driven core/worker end-to-end verification;
it is not an automated sequence of UI menu clicks.

Frozen archive audit: **14 hdw_dedup_engine modules; no deduptool**.
The final ordinary build without verification hooks is kept separately at
`dist\migrated\ChronoName\ChronoName.exe`, preserving earlier distributions.
PyInstaller 6.20.0 / Python 3.13.13 were used. Collection emits the harmless
send2trash.mac warning on Windows; macOS code is not needed by this application.

## Package resolution and coupling audit

Source verification with inherited PYTHONPATH removed for the child process:

```text
Installed distribution: hdw-dedup-engine 0.1.0
Engine module: D:\Coding\HdWDedupEngine\src\hdw_dedup_engine\__init__.py
ChronoName engine class module: hdw_dedup_engine.engine
importlib.util.find_spec('deduptool'): None
```

The session inherited `PYTHONPATH=D:\Coding\DedupTool`; it was cleared only
inside verification/build child processes, never globally changed. Source tests,
GUI checks and final builds pass without it. Frozen engine resolution is
`dist\engine-migration\ChronoName\hdw_dedup_engine\__init__.py`.
An active-source/build audit found no legacy imports/path coupling. Historical
text and backups retain historical names. No obsolete implementation required
deletion; only the absent exporter reference was removed after source verification.

## Files and final working tree

Modified: duplicate_core.py, diagnostics_core.py, test_chrononame_core.py,
requirements.txt, readme.md, py_sources_to_txt.py, preexisting untracked run_pyinstaller.cmd.
Created: build_chrononame.py, test_duplicate_integration.py, this report.
Removed active files: none. Preserved preexisting untracked clean_pyinstaller.cmd.

Expected final git status (all changes intentionally left uncommitted):

```text
 M diagnostics_core.py
 M duplicate_core.py
 M py_sources_to_txt.py
 M readme.md
 M requirements.txt
 M test_chrononame_core.py
?? HDW_DEDUP_ENGINE_MIGRATION_REPORT.md
?? build_chrononame.py
?? clean_pyinstaller.cmd
?? run_pyinstaller.cmd
?? test_duplicate_integration.py
```

## Limits and next step

Inherited engine limitations remain: animated WebP frame-zero hashing,
thumbnail feature dimensions, settings-path behavior and keeper tie limitations.
The Windows report-root normalization issue is adapted within ChronoName rather
than changing engine policy. Action cancellation is cooperative at existing
engine progress checkpoints, not rollback of files already moved.

Manual review remains: run the normal frozen executable, click duplicate report
and quarantine menu actions on a disposable collection, inspect report appearance,
and visually confirm no console flashing. Large real archives and manual HEIC
media/SSIM combinations were not destructively tested. After manual approval,
review/commit these changes and optionally request a push. Person Recognition
migration is a separate task and was not started.

Final ordinary-build checks: archive contains the installed engine and no legacy package or verification hook; offscreen startup stayed running for four seconds and was then stopped by the test; bundled ExifTool returned 13.37. Interactive menu behavior remains the manual check described above.
