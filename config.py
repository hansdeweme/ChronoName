# config.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# part of the ChronoName Project
#
from __future__ import annotations
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "ChronoName"
SETTINGS_FILE = "settings.json"
DEDUP_SETTINGS_FILE = "dedup_settings.json"
DEFAULT_DEDUP_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
)

def _resource_path(filename: str) -> Path:
    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / filename)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / filename)
    candidates.append(Path(__file__).resolve().with_name(filename))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


@dataclass
class FilingAuditConfig:
    tolerance_days: int = 1
    cross_year_forward_days: int = 14
    ignored_folder_names: list[str] = field(default_factory=lambda: ["edits", "exports", "scans"])


@dataclass
class AppConfig:
    """Base configuration for the ChronoName desktop app."""
    app_name: str = APP_NAME
    default_source_folder: str = ""
    default_output_folder: str = ""
    staging_folder: str = "ChronoName Intake"
    name_timezone: str = "Europe/Amsterdam"
    include_device: bool = False
    dry_run_by_default: bool = True
    whatsapp_sent_folder: str = ".\\wa_sent"
    whatsapp_received_folder: str = ".\\wa_received"
    Gallery_Attachments: str = ".\\wa_sent\\attachments"
    In_App_Camera: str = ".\\wa_sent\\in_app"
    Unclassified_or_Cropped: str = ".\\wa_sent\\unclassified"
    Received: str = ".\\wa_received"
    supported_extensions: list[str] = field(default_factory=lambda: ["jpg", "jpeg", "heic", "png", "dng", "cr2", "cr3", "arw", "nef", "raf", "mp4", "mov", "m4v",])
    filing_audit: FilingAuditConfig = field(default_factory=FilingAuditConfig)

def settings_path(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parent
    return root / SETTINGS_FILE

def load_config(path: Path | None = None) -> AppConfig:
    path = path or settings_path()
    defaults = AppConfig()
    if not path.exists():
        save_config(defaults, path)
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Settings file must contain a JSON object: {path}")
    data: dict[str, Any] = asdict(defaults)
    for key in data:
        if key in raw:
            data[key] = raw[key]
    if isinstance(data.get("filing_audit"), dict):
        filing_defaults = asdict(defaults.filing_audit)
        filing_defaults.update(data["filing_audit"])
        data["filing_audit"] = FilingAuditConfig(**filing_defaults)
    return AppConfig(**data)

def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or settings_path()
    path.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

