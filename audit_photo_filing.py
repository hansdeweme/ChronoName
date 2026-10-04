# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
# Compatibility CLI wrapper for the integrated filing audit.
#
# Usage: py -3 audit_photo_filing.py "H:\Galleries\2024"

from __future__ import annotations

import sys
from pathlib import Path

from config import load_config
from filing_audit import run_filing_audit
from models import FilingAuditOptions


def main(root: Path) -> int:
    config = load_config()
    result = run_filing_audit(
        FilingAuditOptions(
            root=root,
            tolerance_days=config.filing_audit.tolerance_days,
            cross_year_forward_days=config.filing_audit.cross_year_forward_days,
            ignored_folder_names=config.filing_audit.ignored_folder_names,
            show_progress=False,
        )
    )

    if result.items:
        print(f"{result.anomaly_count} file finding(s) in {root}")
    else:
        print(f"No file findings in {root}.")
    if result.folder_anomalies:
        print(f"{result.folder_anomaly_count} folder finding(s).")
    print(f"File report: {result.csv_path}")
    print(f"Folder report: {result.folder_csv_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: py -3 audit_photo_filing.py "H:\\Galleries\\2024"')
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
