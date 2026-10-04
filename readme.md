# ChronoName

ChronoName is a desktop workflow for making photo and video filenames follow capture time.

It reads media metadata with ExifTool, builds a reviewable rename plan, and only changes files when you explicitly process that reviewed plan. The normal filename format is:

```text
YYYYMMDD_HHMMSS[_milliseconds][__DEVICE][_counter].ext
```

Examples:

```text
20240118_173839.jpg
20240118_173839_234.jpg
20240118_173839__SONY-A7M3.arw
```

ChronoName grew out of the same photo-library cleanup work as DedupTool. DedupTool helps decide which duplicate files can go; ChronoName makes the remaining files sort and compare reliably by capture time.

## Main Workflow

1. Choose a source folder.
2. Run **Workflow > Audit Timestamp Health**.
3. Optionally create a duplicate report.
4. Run **Workflow > Plan Rename**.
5. Review the log and generated reports.
6. Run **Workflow > Process Rename Plan** only when the plan looks right.

The app now shows a persistent status banner above the log so it is always clear whether the current action is audit-only, report-only, plan-only, copy preparation, or real processing.

## Safety Model

Most actions are review actions and do not modify source files:

- **Audit Timestamp Health** inspects timestamp sources and writes a CSV report.
- **Plan Rename** builds a dry-run rename plan.
- **Create Duplicate Report** writes CSV/HTML reports without moving or renaming files.
- **Analyze Selected WhatsApp Folder** classifies WhatsApp images without changing them.
- **Plan Configured WhatsApp Import** builds a rename plan without renaming files.

The actions that can write files are explicit:

- **Prepare Configured Sent Subfolders** copies WhatsApp sent images into preparation folders. Originals stay in place.
- **Quarantine Duplicate Files** moves files marked duplicate into `<source folder>\.quarantine`.
- **Process Rename Plan** executes the current reviewed plan. The reviewed destinations are authoritative: execution will not silently choose different filenames if the filesystem has changed. Source files are validated against their planned state before being renamed; changed files are reported as stale rather than processed. Successful rename operations are journalled incrementally so recovery information exists even if a run is interrupted. Completed runs also produce rename_log_*.json undo information. Undo is strict: if an original destination has become occupied, ChronoName reports a conflict rather than restoring the file under a different filename.

Undo logs are written as `rename_log_*.json`. The CLI can undo a previous run:

```powershell
py -3 chrononame.py D:\Photos\2024 --undo rename_log_XXXXXXXX.json
```

## Timestamp Health Audit

The timestamp audit is intended as the first check after choosing a source folder. It reports:

- which timestamp source would be used,
- whether the result is high confidence or needs review,
- conflicts between embedded metadata, filename dates, and file modification dates,
- files that should be skipped or inspected manually.

The audit and rename planner use the same timestamp-selection logic. The timestamp decision shown during auditing is therefore the same decision used when constructing the rename plan.

Generated reports are written to:

```text
<source folder>\ChronoName Reports\
```

ChronoName excludes this report folder from later metadata and duplicate scans.

## WhatsApp Images

WhatsApp media often has weak or stripped metadata, so ChronoName has a separate workflow for WhatsApp images.

Configured defaults in `settings.json`:

```json
"whatsapp_sent_folder": ".\\wa_sent",
"whatsapp_received_folder": ".\\wa_received",
"Gallery_Attachments": ".\\wa_sent\\attachments",
"In_App_Camera": ".\\wa_sent\\in_app",
"Unclassified_or_Cropped": ".\\wa_sent\\unclassified",
"Received": ".\\wa_received"
```

Sent images can be prepared into subfolders before planning:

- gallery attachments,
- in-app camera images,
- unclassified or cropped images.

Received images are processed as one folder. They are usually not duplicates of the local photo collection, but they are often WhatsApp-processed and may have little useful metadata.

Regular WhatsApp movies are usually downgraded enough that they may not be worth archiving as primary originals. Movies sent as WhatsApp documents are a different case and can be treated as normal media files.

## Duplicate Reports

Duplicate analysis is report-only by default. It produces CSV/HTML reports without changing the source collection. Reports use consistent timestamped names and are written to the source folder's `ChronoName Reports` subfolder.

After reviewing the duplicate report, **Workflow > Quarantine Duplicate Files** can be used to move the files marked `DUPLICATE` into a local `.quarantine` folder inside the selected source folder. This keeps the operation non-destructive: duplicates leave the active folder tree but remain available for manual inspection or recovery.

Duplicate detection is provided by the shared deduptool package rather than a ChronoName-specific copy of the duplicate engine. Matching, clustering, keeper selection, reporting and quarantine therefore use the same implementation as DedupTool itself.

Near-duplicate matching no longer accepts dHash alone; pHash and wHash are also used to corroborate perceptual matches.

## Running

Start the desktop app:

```powershell
py -3 main.py
```

The legacy CLI is still available:

```powershell
py -3 chrononame.py D:\Photos\2024 --dry-run --name-tz Europe/Amsterdam --skip-already
py -3 chrononame.py D:\Photos\2024 --name-tz Europe/Amsterdam --skip-already
```

ChronoName uses ExifTool for metadata extraction. The download package includes ExifTool; keep the executable in the ChronoName folder together with its exiftool_files subfolder. An existing ExifTool installation on PATH can also be used if supported by the current configuration.

Runtime Python packages used by the current app include PyQt6, Pillow, pillow-heif, and the scientific/image stack used by duplicate detection where available.

Requirements are installed by: py -3 -m pip install -r requirements.txt 

## Pre production testing

Before first use: test ChronoName on a copy or small subset of your media collection. Review timestamp audits, duplicate reports and rename plans before executing filesystem changes. Keep normal backups of important photo archives; quarantine and undo facilities are safety mechanisms, not replacements for backups.

## More Background

Original design notes: <https://code2trade.dev/chrononame-a-deterministic-workflow-for-renaming-photos-by-capture-time/>

Background for the current version: 

Background for DedupTool: <https://code2trade.dev/from-a-finding-duplicates-script-to-the-deduptool-engineering-a-safe-deterministic-photo-deduplication-tool-for-windows/>
