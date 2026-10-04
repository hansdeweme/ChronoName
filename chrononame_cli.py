# chrononame_cli.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# CLI entrypoint
#

from __future__ import annotations
import argparse
import sys
from pathlib import Path
# local imports
from chrononame_core import build_rename_plan, execute_rename_plan, undo_renames
from models import RenameOptions

def main() -> int:
    ap = argparse.ArgumentParser(description="Batch rename photos/videos in a year folder by capture time.")
    ap.add_argument("root", type=Path, help="Top-level year folder, e.g. D:\\Photos\\2021")
    ap.add_argument("--name-tz", default="Europe/Amsterdam", help="Timezone used for output filenames (IANA tz, e.g. Europe/Amsterdam).")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change, do not rename")
    ap.add_argument("--include-device", action="store_true", help="Append __MAKE-MODEL to filename")
    ap.add_argument("--skip-already", action="store_true", help="Skip files that already look timestamped")
    ap.add_argument("--log", type=Path, default=None, help="Path for rename log JSON (default auto)")
    ap.add_argument("--undo", type=Path, default=None, help="Undo a previous run using its JSON log")
    ap.add_argument("--progress-every", type=int, default=100, help="Progress update interval (items). 0 disables.")
    ap.add_argument("--no-progress", action="store_true", help="Disable progress output")
    ap.add_argument("--manifest", type=Path, default=None, help="Write a collection manifest JSON (default auto when enabled).")
    ap.add_argument("--write-manifest", action="store_true", help="Write a collection manifest describing the normalized archive state.")
    ap.add_argument("--manifest-hash", action="store_true", help="Include SHA-256 hashes in the collection manifest (slower).")
    args = ap.parse_args()

    if args.undo:
        result = undo_renames(args.undo, dry_run=args.dry_run)
        for skipped in result.skipped:
            print(f"SKIP: {skipped}")
        print("Undo complete.")
        return 0

    options = RenameOptions(
        root=args.root,
        name_tz=args.name_tz,
        dry_run=args.dry_run,
        include_device=args.include_device,
        skip_already=args.skip_already,
        log_path=args.log,
        write_manifest=args.write_manifest,
        manifest_path=args.manifest,
        manifest_hash=args.manifest_hash,
        progress_every=args.progress_every,
        show_progress=not args.no_progress,
    )

    try:
        plan = build_rename_plan(options)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not plan.metadata_count:
        print("No supported media files found.")
        return 0

    if not plan.operations:
        print("Nothing to rename.")
        return 0

    print(f"Planned renames: {len(plan.operations)}")
    for operation in plan.operations[:20]:
        print(
            f"{operation.old_path.name}  ->  "
            f"{operation.new_path.name}  ({operation.timestamp_source})"
        )
    if len(plan.operations) > 20:
        print(f"... and {len(plan.operations)-20} more")

    if args.dry_run:
        print("[dry-run] No changes written. Log not saved.")
        if args.write_manifest:
            print("[dry-run] Manifest not written because files were not renamed.")
        return 0

    result = execute_rename_plan(plan, options)
    if result.skipped:
        print("Processing failures:", file=sys.stderr)
        for skipped in result.skipped:
            print(f"[FAIL] {skipped}", file=sys.stderr)
        print("Build and review a new rename plan before processing again.", file=sys.stderr)

    print(f"Done. Renamed {result.renamed_count} files.")
    if result.log_path:
        print(f"Undo log saved to: {result.log_path}")
    if result.journal_path:
        print(f"Undo journal saved to: {result.journal_path}")
    if result.manifest_path:
        print(f"Collection manifest saved to: {result.manifest_path}")
    return 1 if result.skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
