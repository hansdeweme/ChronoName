# report_paths.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# Centralized report naming and placement.
#

from __future__ import annotations

import time
from pathlib import Path


REPORTS_FOLDER_NAME = "ChronoName Reports"


def report_dir_for(root: Path) -> Path:
    return root / REPORTS_FOLDER_NAME


def report_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def timestamped_report_path(root: Path, report_kind: str, extension: str) -> Path:
    return report_path(root, report_kind, report_timestamp(), extension)


def report_path(root: Path, report_kind: str, timestamp: str, extension: str) -> Path:
    safe_extension = extension.lstrip(".")
    return report_dir_for(root) / f"{report_kind}_{timestamp}.{safe_extension}"

