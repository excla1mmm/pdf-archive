from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppConfig
from .utils import safe_filename_part

SOURCE_TYPE_PAPER = "paper_scan"
SOURCE_TYPE_DIGITAL = "digital"
SOURCE_TYPE_UNKNOWN = "unknown"
SOURCE_TYPE_AUTO = "auto"


@dataclass(frozen=True)
class ArchiveCodeInfo:
    code: str
    source_type: str
    source: str
    physical_document: bool
    barcode_required: bool

    def as_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "source_type": self.source_type,
            "source": self.source,
            "physical_document": self.physical_document,
            "barcode_required": self.barcode_required,
        }


def infer_source_type(config: AppConfig, pdf_path: Path, barcode: str) -> str:
    source_from_folder = _source_type_from_input_folder(config, pdf_path)
    if source_from_folder != SOURCE_TYPE_UNKNOWN:
        return source_from_folder

    default = normalize_source_type(config.archive_code.default_source_type)
    if default == SOURCE_TYPE_AUTO:
        return SOURCE_TYPE_PAPER if barcode else SOURCE_TYPE_DIGITAL
    return default


def normalize_source_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "paper": SOURCE_TYPE_PAPER,
        "scan": SOURCE_TYPE_PAPER,
        "paper_scan": SOURCE_TYPE_PAPER,
        "papier": SOURCE_TYPE_PAPER,
        "digital": SOURCE_TYPE_DIGITAL,
        "digital_only": SOURCE_TYPE_DIGITAL,
        "auto": SOURCE_TYPE_AUTO,
        "unknown": SOURCE_TYPE_UNKNOWN,
        "": SOURCE_TYPE_UNKNOWN,
    }
    return aliases.get(text, SOURCE_TYPE_UNKNOWN)


def assign_archive_code(
    config: AppConfig,
    source_type: str,
    document_date: str | None,
    barcode: str,
    *,
    commit: bool,
) -> ArchiveCodeInfo:
    source_type = normalize_source_type(source_type)
    if source_type == SOURCE_TYPE_AUTO:
        source_type = SOURCE_TYPE_PAPER if barcode else SOURCE_TYPE_DIGITAL

    barcode_required = source_type == SOURCE_TYPE_PAPER and config.archive_code.require_barcode_for_paper
    if source_type == SOURCE_TYPE_PAPER:
        return ArchiveCodeInfo(
            code=barcode,
            source_type=source_type,
            source="barcode" if barcode else "missing",
            physical_document=True,
            barcode_required=barcode_required,
        )

    if source_type == SOURCE_TYPE_DIGITAL and config.archive_code.enabled:
        code = _reserve_code(config, config.archive_code.digital_prefix, _code_year(document_date), commit=commit)
        return ArchiveCodeInfo(
            code=code,
            source_type=source_type,
            source="generated",
            physical_document=False,
            barcode_required=False,
        )

    return ArchiveCodeInfo(
        code=barcode,
        source_type=source_type,
        source="barcode" if barcode else "missing",
        physical_document=False,
        barcode_required=False,
    )


def resolve_review_archive_code(
    config: AppConfig,
    source_type: str,
    document_date: str | None,
    barcode: str,
    current_code: str,
    override_code: Any,
) -> ArchiveCodeInfo:
    source_type = normalize_source_type(source_type)
    if source_type in {SOURCE_TYPE_AUTO, SOURCE_TYPE_UNKNOWN}:
        source_type = SOURCE_TYPE_PAPER if barcode else SOURCE_TYPE_DIGITAL

    override_text = str(override_code or "").strip()
    if override_text:
        return ArchiveCodeInfo(
            code=override_text,
            source_type=source_type,
            source="manual",
            physical_document=source_type == SOURCE_TYPE_PAPER,
            barcode_required=source_type == SOURCE_TYPE_PAPER and config.archive_code.require_barcode_for_paper,
        )

    current_code = str(current_code or "").strip()
    if current_code:
        return ArchiveCodeInfo(
            code=current_code,
            source_type=source_type,
            source="existing",
            physical_document=source_type == SOURCE_TYPE_PAPER,
            barcode_required=source_type == SOURCE_TYPE_PAPER and config.archive_code.require_barcode_for_paper,
        )

    return assign_archive_code(config, source_type, document_date, barcode, commit=True)


def _source_type_from_input_folder(config: AppConfig, pdf_path: Path) -> str:
    try:
        relative = pdf_path.resolve().relative_to(config.input_dir.resolve())
    except ValueError:
        return SOURCE_TYPE_UNKNOWN
    if len(relative.parts) < 2:
        return SOURCE_TYPE_UNKNOWN

    top_folder = relative.parts[0].casefold()
    if top_folder == config.archive_code.paper_input_folder.casefold():
        return SOURCE_TYPE_PAPER
    if top_folder == config.archive_code.digital_input_folder.casefold():
        return SOURCE_TYPE_DIGITAL
    return SOURCE_TYPE_UNKNOWN


def _code_year(document_date: str | None) -> str:
    text = str(document_date or "")
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return str(datetime.now().year)


def _reserve_code(config: AppConfig, prefix: str, year: str, *, commit: bool) -> str:
    counter_file = config.archive_code.counter_file
    counters = _read_counters(counter_file)
    key = f"{safe_filename_part(prefix, fallback='D', max_length=8).upper()}-{year}"
    next_number = int(counters.get(key, 0)) + 1
    if commit:
        counters[key] = next_number
        _write_counters(counter_file, counters)
    return f"{key}-{next_number:0{config.archive_code.number_width}d}"


def _read_counters(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    counters: dict[str, int] = {}
    for key, value in data.items():
        try:
            counters[str(key)] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return counters


def _write_counters(path: Path, counters: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(counters, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
