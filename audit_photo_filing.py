# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Utility to audit photo filing in a year-based folder structure, checking file dates (from names) against folder date ranges and the year.
# Usage: python audit_photo_filing.py "H:\Galleries\2024"
import sys, re, csv
from pathlib import Path
from datetime import date, timedelta

# ---------- config ----------
SUPPORTED_EXT = {".jpg",".jpeg",".heic",".png",".dng",".cr2",".cr3",".arw",".nef",".raf",
                 ".mp4",".mov",".m4v"}
TOLERANCE_DAYS = 1                 # small forgiveness for DST/metadata quirks
CROSS_YEAR_FORWARD_DAYS = 14       # allow last-range spillover into next year
IGNORE_FOLDERS = {"edits","exports","scans"}  # case-insensitive names to skip
# ----------------------------

FILE_RE = re.compile(
    r"^(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})_(?P<h>\d{2})(?P<m>\d{2})(?P<s>\d{2})"
    r"(?:_(?P<ms>\d{3}))?(?:__.*)?(?:_\d{3})?$",
    re.IGNORECASE
)
FOLDER_RE = re.compile(
    r"^(?P<start>\d{8})(?:_(?P<end>\d{8}))?(?:-.+)?$",
    re.IGNORECASE
)

def yyyymmdd_to_date(s: str) -> date:
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))

def parse_file_date_from_name(name: str) -> date | None:
    base = name.rsplit(".", 1)[0]  # drop extension if present
    m = FILE_RE.match(base)
    if not m:
        return None
    return date(int(m["Y"]), int(m["M"]), int(m["D"]))

def parse_folder_range_from_name(name: str) -> tuple[date,date] | None:
    m = FOLDER_RE.match(name)
    if not m:
        return None
    start = yyyymmdd_to_date(m["start"])
    end = yyyymmdd_to_date(m["end"]) if m["end"] else start
    if end < start:
        start, end = end, start
    return start, end

def os_walk(root: Path):
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        dpath = Path(dirpath)
        dirnames[:] = [n for n in dirnames if n.lower() not in IGNORE_FOLDERS]
        yield dpath, [dpath / n for n in dirnames], filenames

def collect_dated_folder_ranges(year_root: Path) -> dict[Path, tuple[date,date]]:
    ranges = {}
    for d, _, _ in os_walk(year_root):
        r = parse_folder_range_from_name(d.name)
        if r:
            ranges[d] = r
    return ranges

def nearest_ancestor_range(path: Path, ranges: dict[Path, tuple[date,date]]):
    cur = path
    while True:
        if cur in ranges:
            return cur, ranges[cur]
        if cur.parent == cur:
            break
        cur = cur.parent
    return None, None

def analyze_folders(year_root: Path, ranges: dict[Path, tuple[date,date]], yr: int):
    """Return list of folder-level anomalies with reasons."""
    anomalies = []
    jan1_next = date(yr+1,1,1)
    limit = jan1_next + timedelta(days=CROSS_YEAR_FORWARD_DAYS)

    for p, (s, e) in ranges.items():
        # Skip the year root itself
        if p == year_root: 
            continue

        # Folder starts before the audited year
        if s.year < yr:
            anomalies.append({"folder": str(p),
                              "range": f"{s}..{e}",
                              "reason": "FolderStartsBeforeYear"})

        # Folder starts after the audited year
        elif s.year > yr:
            anomalies.append({"folder": str(p),
                              "range": f"{s}..{e}",
                              "reason": "FolderStartsAfterYear"})

        # Cross-year forward spill allowed up to limit
        if s.year == yr and e.year == yr+1:
            if e > limit:
                anomalies.append({"folder": str(p),
                                  "range": f"{s}..{e}",
                                  "reason": f"CrossYearOverrun(>{CROSS_YEAR_FORWARD_DAYS}d)"})

        # Fully outside the year (both in another year)
        if (s.year < yr and e.year < yr) or (s.year > yr and e.year > yr):
            anomalies.append({"folder": str(p),
                              "range": f"{s}..{e}",
                              "reason": "FolderOutsideYear"})

    return anomalies

def main(year_root: Path):
    if not year_root.is_dir():
        print(f"Not a directory: {year_root}", file=sys.stderr); sys.exit(1)

    yr = int(year_root.name)
    year_lo = date(yr,1,1) - timedelta(days=TOLERANCE_DAYS)
    year_hi = date(yr,12,31) + timedelta(days=TOLERANCE_DAYS)
    year_range = (year_lo, year_hi)

    # Index dated folder ranges under this year
    ranges = collect_dated_folder_ranges(year_root)
    # Analyze folder-level anomalies (placement/overrun)
    folder_anoms = analyze_folders(year_root, ranges, yr)

    suspects = []
    per_folder_counts: dict[Path,int] = {}

    for d, _, files in os_walk(year_root):
        for fn in files:
            ext = Path(fn).suffix.lower()
            if ext not in SUPPORTED_EXT:
                continue            
            fdt = parse_file_date_from_name(Path(fn).stem)
            fpath = d / fn

            if not fdt:
                per_folder_counts[d] = per_folder_counts.get(d,0) + 1
                suspects.append({
                    "reason":"NameParseFail",
                    "file_date":"",
                    "file_path":str(fpath),
                    "checked_against":"",
                    "allowed_range":""
                })
                continue

            # Prefer nearest dated ancestor if present
            anc = nearest_ancestor_range(d, ranges)
            if anc[0] is not None:
                anc_path, (s, e) = anc

                # Accept cross-year folder if it starts in this year and ends within allowed forward window
                if s.year == yr and e.year == yr+1:
                    limit = date(yr+1,1,1) + timedelta(days=CROSS_YEAR_FORWARD_DAYS)
                    allowed_lo, allowed_hi = s, min(e, limit)
                else:
                    allowed_lo, allowed_hi = s, e

                if not (allowed_lo - timedelta(days=TOLERANCE_DAYS) <= fdt <= allowed_hi + timedelta(days=TOLERANCE_DAYS)):
                    per_folder_counts[d] = per_folder_counts.get(d,0) + 1
                    suspects.append({
                        "reason":"FolderOutOfRange",
                        "file_date":fdt.isoformat(),
                        "file_path":str(fpath),
                        "checked_against":str(anc_path),
                        "allowed_range":f"{allowed_lo}..{allowed_hi}"
                    })
                # If it fits, no further year check needed
                continue

            # No dated ancestor → fall back to year range check
            if not (year_range[0] <= fdt <= year_range[1]):
                per_folder_counts[d] = per_folder_counts.get(d,0) + 1
                suspects.append({
                    "reason":"YearMismatch",
                    "file_date":fdt.isoformat(),
                    "file_path":str(fpath),
                    "checked_against":str(year_root),
                    "allowed_range":f"{year_range[0]}..{year_range[1]}"
                })

    # Console summary
    if suspects:
        print(f"Suspects by folder in {year_root}:")
        for folder, cnt in sorted(per_folder_counts.items(), key=lambda x: (str(x[0]).lower(), -x[1])):
            print(f"{folder}  ->  {cnt} suspect(s)")
    else:
        print(f"No suspect files in {year_root}.")

    # Write files CSV
    out_files = year_root.parent / f"misfile_report_{year_root.name}.csv"
    with out_files.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["reason","file_date","file_path","checked_against","allowed_range"])
        w.writeheader(); w.writerows(suspects)
    print(f"File report: {out_files}")

    # Write folder anomalies CSV
    out_folders = year_root.parent / f"folder_anomalies_{year_root.name}.csv"
    with out_folders.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["folder","range","reason"])
        w.writeheader(); w.writerows(folder_anoms)
    print(f"Folder report: {out_folders}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python audit_photo_filing.py \"H:\\Galleries\\2024\"")
        sys.exit(2)
    main(Path(sys.argv[1]))
