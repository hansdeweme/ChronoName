# chrononame.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# compatibility wrapper/re-export layer and script entry point
#

from __future__ import annotations
# local imports
from chrononame_cli import main
from chrononame_core import (
    already_good_name,
    build_manifest_entry,
    build_rename_plan,
    choose_best_dt,
    execute_rename_plan,
    next_free_name,
    parse_exif_dt,
    sanitize,
    scan_metadata,
    sha256_file,
    undo_renames,
)
from exiftool_adapter import (
    SUPPORTED_EXT,
    call_exiftool_json,
    call_exiftool_json_with_spinner,
    have_exiftool,
)
from models import (
    ManifestPlanEntry,
    ProgressCallback,
    RenameOperation,
    RenameOptions,
    RenamePlan,
    RenameResult,
    UndoResult,
)

__all__ = [
    "SUPPORTED_EXT",
    "ManifestPlanEntry",
    "ProgressCallback",
    "RenameOperation",
    "RenameOptions",
    "RenamePlan",
    "RenameResult",
    "UndoResult",
    "already_good_name",
    "build_manifest_entry",
    "build_rename_plan",
    "call_exiftool_json",
    "call_exiftool_json_with_spinner",
    "choose_best_dt",
    "execute_rename_plan",
    "have_exiftool",
    "main",
    "next_free_name",
    "parse_exif_dt",
    "sanitize",
    "scan_metadata",
    "sha256_file",
    "undo_renames",
]


if __name__ == "__main__":
    raise SystemExit(main())

