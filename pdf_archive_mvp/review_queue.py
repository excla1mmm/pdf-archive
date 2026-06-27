from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive_code import normalize_source_type, resolve_review_archive_code
from .config import AppConfig
from .naming import build_filename, resolve_manual_category
from .pdf_tools import write_pdf_with_metadata
from .sidecar import json_sidecar_path, write_json, write_xml, xml_sidecar_path
from .utils import now_iso, parse_iso_date, safe_filename_part


@dataclass(frozen=True)
class QueuedItem:
    item_id: str
    pdf_path: Path
    draft_json_path: Path

    @property
    def metadata_path(self) -> Path:
        return self.draft_json_path


def queue_root(config: AppConfig) -> Path:
    return config.archive_dir / "_Queue"


def queue_db_path(config: AppConfig) -> Path:
    return queue_root(config) / "review_queue.sqlite3"


def init_review_queue(config: AppConfig) -> None:
    root = queue_root(config)
    (root / "pending").mkdir(parents=True, exist_ok=True)
    (root / "completed").mkdir(parents=True, exist_ok=True)
    _migrate_legacy_sqlite_queue(config)


def enqueue_review_item(config: AppConfig, source_pdf: Path, payload: dict[str, Any]) -> QueuedItem:
    init_review_queue(config)
    item_id = str(payload.get("archive_id") or "").strip()
    if not item_id:
        raise ValueError("Cannot queue document without archive_id.")

    queued_at = now_iso()
    original_name = source_pdf.name
    base_name = safe_filename_part(source_pdf.stem, fallback="document", max_length=80)
    pending_pdf = _unique_pdf_with_sidecars(queue_root(config) / "pending" / f"{base_name}_{item_id[:8]}.pdf")
    metadata_path = json_sidecar_path(pending_pdf)

    pending_pdf.parent.mkdir(parents=True, exist_ok=True)
    if config.delete_source_after_success:
        shutil.move(str(source_pdf), str(pending_pdf))
    else:
        shutil.copy2(source_pdf, pending_pdf)

    source = payload.setdefault("source", {})
    source.setdefault("original_filename", original_name)
    source["queued_from_path"] = str(source_pdf)
    source["path"] = str(pending_pdf)

    payload["status"] = "pending_review"
    payload["workflow"] = {
        "stage": "review",
        "status": "pending_review",
        "metadata_storage": "json_sidecar",
    }
    payload["metadata_sidecar"] = {
        "format": "json",
        "path": str(metadata_path),
        "role": "analysis_result",
    }
    payload["queue"] = {
        "id": item_id,
        "status": "pending_review",
        "queued_at": queued_at,
        "updated_at": queued_at,
        "storage": "json_sidecar",
        "pdf_path": str(pending_pdf),
        "metadata_path": str(metadata_path),
        "draft_json_path": str(metadata_path),
    }
    payload["manual_review"] = {
        "approved": False,
        "approved_at": "",
        "overrides": {},
    }

    write_json(metadata_path, payload)
    return QueuedItem(item_id=item_id, pdf_path=pending_pdf, draft_json_path=metadata_path)


def list_review_items(config: AppConfig, include_completed: bool = False) -> list[dict[str, Any]]:
    init_review_queue(config)
    items: list[dict[str, Any]] = []

    for sidecar_path in _iter_json_sidecars(queue_root(config) / "pending"):
        payload = _load_json(sidecar_path)
        status = _payload_status(payload)
        if include_completed or status == "pending_review":
            items.append(_payload_to_summary(config, payload, sidecar_path))

    if include_completed:
        for sidecar_path in _iter_json_sidecars(queue_root(config) / "completed"):
            payload = _load_json(sidecar_path)
            items.append(_payload_to_summary(config, payload, sidecar_path))

    return sorted(items, key=lambda item: (item.get("queued_at", ""), item.get("original_filename", "")))


def review_queue_snapshot(config: AppConfig, include_completed: bool = False) -> dict[str, Any]:
    root = queue_root(config)
    return {
        "metadata_storage": "json_sidecar",
        "queue_root": str(root),
        "pending_dir": str(root / "pending"),
        "completed_dir": str(root / "completed"),
        "legacy_queue_db": str(queue_db_path(config)),
        "queue_db": "",
        "items": list_review_items(config, include_completed=include_completed),
        "categories": [
            {
                "id": category.id,
                "name": category.name,
                "folder": category.folder,
                "description": category.description,
            }
            for category in config.categories
        ],
    }


def finalize_review_item(config: AppConfig, item_id: str, overrides: dict[str, Any]) -> dict[str, Any]:
    init_review_queue(config)
    sidecar_path, payload = _find_pending_item(config, item_id)
    status = _payload_status(payload)
    if status != "pending_review":
        raise ValueError(f"Review queue item is not pending: {item_id} ({status})")

    pdf_path = _payload_pdf_path(config, payload, sidecar_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Queued PDF not found: {pdf_path}")

    detected_before_review = {
        "barcode": payload.get("barcode", ""),
        "archive_code": payload.get("archive_code", ""),
        "archive_code_info": payload.get("archive_code_info", {}),
        "source_type": payload.get("source_type", ""),
        "physical_document": payload.get("physical_document", False),
        "document_date": payload.get("document_date", ""),
        "category": payload.get("category", {}),
        "sender": payload.get("sender", ""),
        "title": payload.get("title", ""),
        "short_filename_title": payload.get("short_filename_title", ""),
        "confidence": payload.get("confidence", 0.0),
        "review_reasons": payload.get("review_reasons", []),
    }

    document_date = _resolve_date(overrides.get("document_date"), payload.get("document_date", ""))
    barcode = _resolve_text(overrides.get("barcode"), payload.get("barcode", ""))
    source_type = normalize_source_type(_resolve_text(overrides.get("source_type"), payload.get("source_type", "")))
    archive_code_info = resolve_review_archive_code(
        config,
        source_type,
        document_date,
        barcode,
        payload.get("archive_code", ""),
        overrides.get("archive_code"),
    )
    archive_code = archive_code_info.code
    sender = _resolve_text(overrides.get("sender"), payload.get("sender", ""))
    title = _resolve_text(overrides.get("title"), payload.get("title", ""))
    short_title = _resolve_text(overrides.get("short_filename_title"), payload.get("short_filename_title", "Dokument"))

    current_category = payload.get("category", {})
    category_id = _resolve_text(overrides.get("category_id"), current_category.get("id", "other"))
    category_name = _resolve_text(overrides.get("category_name"), current_category.get("name", ""))
    category_folder, category_payload = resolve_manual_category(config, category_id, category_name)

    target_year = document_date[:4] if document_date else config.unknown_year_folder
    classification_for_filename = {
        "sender": sender,
        "short_filename_title": short_title,
    }
    filename = build_filename(document_date, category_folder, classification_for_filename, archive_code)
    target_dir = config.archive_dir / target_year / category_folder
    target_pdf = _unique_pdf_with_sidecars(target_dir / filename)
    target_json = json_sidecar_path(target_pdf)
    target_xml = xml_sidecar_path(target_pdf)
    approved_at = now_iso()
    completed_json = _unique_completed_sidecar(config, item_id)

    payload["status"] = "archived"
    payload["workflow"] = {
        "stage": "post_processing",
        "status": "archived",
        "metadata_storage": "json_sidecar",
    }
    payload["detected_before_review"] = detected_before_review
    payload["barcode"] = barcode
    payload["archive_code"] = archive_code
    payload["archive_code_info"] = archive_code_info.as_payload()
    payload["source_type"] = archive_code_info.source_type
    payload["physical_document"] = archive_code_info.physical_document
    payload["document_date"] = document_date
    payload["category"] = category_payload
    payload["sender"] = sender
    payload["title"] = title
    payload["short_filename_title"] = short_title
    payload["target"] = {
        "path": str(target_pdf),
        "year": target_year,
        "folder": str(target_dir),
        "filename": target_pdf.name,
        "json_sidecar": str(target_json),
        "xml_sidecar": str(target_xml) if config.create_xml else "",
    }
    payload["metadata_sidecar"] = {
        "format": "json",
        "path": str(target_json),
        "xml_path": str(target_xml) if config.create_xml else "",
        "role": "final_metadata",
    }
    payload["review_required"] = False
    payload["review_reasons"] = []
    payload["manual_review"] = {
        "approved": True,
        "approved_at": approved_at,
        "overrides": {
            "document_date": document_date,
            "barcode": barcode,
            "archive_code": archive_code,
            "source_type": archive_code_info.source_type,
            "category_id": category_payload["id"],
            "category_name": category_payload["name"],
            "sender": sender,
            "title": title,
            "short_filename_title": short_title,
        },
    }
    payload["queue"] = {
        **payload.get("queue", {}),
        "status": "approved",
        "updated_at": approved_at,
        "final_pdf_path": str(target_pdf),
        "final_json_path": str(target_json),
        "final_xml_path": str(target_xml) if config.create_xml else "",
        "completed_metadata_path": str(completed_json),
    }

    target_dir.mkdir(parents=True, exist_ok=True)
    metadata_written, metadata_error = write_pdf_with_metadata(
        pdf_path,
        target_pdf,
        {
            "Barcode": barcode,
            "ArchiveCode": archive_code,
            "ArchiveId": payload["archive_id"],
            "ArchiveSourceType": archive_code_info.source_type,
            "ArchivePhysicalDocument": str(archive_code_info.physical_document).lower(),
            "DocumentDate": document_date,
            "DocumentCategory": category_payload["id"],
            "DocumentCategoryName": category_payload["name"],
            "ArchiveReviewRequired": "false",
            "ArchiveReviewReasons": "",
            "ArchiveReviewApproved": "true",
            "ArchiveReviewApprovedAt": approved_at,
            "ArchiveProcessedAt": payload.get("processed_at", approved_at),
        },
    )
    payload["pdf_metadata_written"] = metadata_written
    if metadata_error:
        payload.setdefault("extraction", {}).setdefault("warnings", []).append(
            f"PDF metadata write failed during review approval; original copied: {metadata_error}"
        )

    write_json(target_json, payload)
    if config.create_xml:
        write_xml(target_xml, payload)
    write_json(completed_json, payload)

    if pdf_path.resolve() != target_pdf.resolve() and pdf_path.exists():
        pdf_path.unlink()
    if sidecar_path.exists():
        sidecar_path.unlink()

    return {
        "id": item_id,
        "status": "approved",
        "target_pdf": str(target_pdf),
        "json": str(target_json),
        "xml": str(target_xml) if config.create_xml else "",
        "queue_completed_json": str(completed_json),
        "pdf_metadata_written": metadata_written,
    }


def _migrate_legacy_sqlite_queue(config: AppConfig) -> None:
    db_path = queue_db_path(config)
    if not db_path.exists():
        return

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM review_queue WHERE status = ?", ("pending_review",)).fetchall()
    except sqlite3.Error:
        return

    for row in rows:
        pdf_path = Path(str(row["pdf_path"]))
        if not pdf_path.exists():
            continue

        metadata_path = json_sidecar_path(pdf_path)
        if metadata_path.exists():
            continue

        payload = _load_legacy_payload(row)
        if not payload:
            continue

        migrated_at = now_iso()
        item_id = str(row["id"])
        source = payload.setdefault("source", {})
        source.setdefault("original_filename", row["original_filename"])
        source.setdefault("queued_from_path", row["original_path"])
        source["path"] = str(pdf_path)

        payload["status"] = "pending_review"
        payload["workflow"] = {
            "stage": "review",
            "status": "pending_review",
            "metadata_storage": "json_sidecar",
        }
        payload["metadata_sidecar"] = {
            "format": "json",
            "path": str(metadata_path),
            "role": "analysis_result",
            "migrated_from": str(db_path),
        }
        payload["queue"] = {
            **payload.get("queue", {}),
            "id": item_id,
            "status": "pending_review",
            "queued_at": str(row["queued_at"]),
            "updated_at": migrated_at,
            "storage": "json_sidecar",
            "pdf_path": str(pdf_path),
            "metadata_path": str(metadata_path),
            "draft_json_path": str(metadata_path),
            "legacy_db_path": str(db_path),
        }
        payload.setdefault(
            "manual_review",
            {
                "approved": False,
                "approved_at": "",
                "overrides": {},
            },
        )
        write_json(metadata_path, payload)


def _load_legacy_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        draft_path = Path(row["draft_json_path"])
        if draft_path.exists():
            data = json.loads(draft_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass

    try:
        data = json.loads(row["data_json"])
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _iter_json_sidecars(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".json")


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Metadata sidecar must contain a JSON object: {path}")
    return data


def _find_pending_item(config: AppConfig, item_id: str) -> tuple[Path, dict[str, Any]]:
    candidate = Path(item_id)
    if candidate.exists() and candidate.is_file():
        payload = _load_json(candidate)
        return candidate, payload

    for sidecar_path in _iter_json_sidecars(queue_root(config) / "pending"):
        payload = _load_json(sidecar_path)
        queue = payload.get("queue", {})
        identifiers = {
            str(queue.get("id", "")),
            str(payload.get("archive_id", "")),
            sidecar_path.name,
            sidecar_path.stem,
        }
        if item_id in identifiers:
            return sidecar_path, payload

    raise ValueError(f"Review queue item not found: {item_id}")


def _payload_status(payload: dict[str, Any]) -> str:
    queue = payload.get("queue", {})
    return str(queue.get("status") or payload.get("status") or "pending_review").strip()


def _payload_pdf_path(config: AppConfig, payload: dict[str, Any], sidecar_path: Path) -> Path:
    queue = payload.get("queue", {})
    source = payload.get("source", {})
    for value in (queue.get("pdf_path"), source.get("path")):
        if value:
            return _resolve_stored_path(config, value)

    if sidecar_path.name.lower().endswith(".json"):
        return sidecar_path.with_name(sidecar_path.name[:-5])
    return sidecar_path.with_suffix(".pdf")


def _resolve_stored_path(config: AppConfig, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (config.config_path.parent / path).resolve()


def _payload_to_summary(config: AppConfig, payload: dict[str, Any], sidecar_path: Path) -> dict[str, Any]:
    category = payload.get("category", {})
    target = payload.get("target", {})
    queue = payload.get("queue", {})
    source = payload.get("source", {})
    pdf_path = _payload_pdf_path(config, payload, sidecar_path)
    item_id = str(queue.get("id") or payload.get("archive_id") or sidecar_path.stem)
    category_id = str(category.get("id", ""))
    category_name = str(category.get("name", ""))
    category_folder = str(category.get("folder", ""))
    if category_id in config.categories_by_id:
        fixed_category = config.categories_by_id[category_id]
        category_name = fixed_category.name
        category_folder = fixed_category.folder

    return {
        "id": item_id,
        "status": _payload_status(payload),
        "queued_at": str(queue.get("queued_at", "")),
        "updated_at": str(queue.get("updated_at", "")),
        "original_filename": str(source.get("original_filename") or pdf_path.name),
        "pdf_path": str(pdf_path),
        "metadata_path": str(sidecar_path),
        "draft_json_path": str(sidecar_path),
        "final_pdf_path": str(queue.get("final_pdf_path") or target.get("path") or ""),
        "document_date": payload.get("document_date", ""),
        "barcode": payload.get("barcode", ""),
        "archive_code": payload.get("archive_code", ""),
        "archive_code_info": payload.get("archive_code_info", {}),
        "source_type": payload.get("source_type", ""),
        "physical_document": payload.get("physical_document", False),
        "category_id": category_id,
        "category_name": category_name,
        "category_folder": category_folder,
        "sender": payload.get("sender", ""),
        "title": payload.get("title", ""),
        "short_filename_title": payload.get("short_filename_title", ""),
        "confidence": payload.get("confidence", 0.0),
        "review_required": payload.get("review_required", True),
        "review_reasons": payload.get("review_reasons", []),
        "proposed_filename": target.get("filename", ""),
        "text_excerpt": payload.get("text_excerpt", ""),
    }


def _unique_pdf_with_sidecars(path: Path) -> Path:
    if _pdf_slot_available(path):
        return path

    parent = path.parent
    stem = path.stem
    suffix = path.suffix or ".pdf"
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if _pdf_slot_available(candidate):
            return candidate
        counter += 1


def _pdf_slot_available(path: Path) -> bool:
    return not path.exists() and not json_sidecar_path(path).exists() and not xml_sidecar_path(path).exists()


def _unique_completed_sidecar(config: AppConfig, item_id: str) -> Path:
    completed_dir = queue_root(config) / "completed"
    completed_dir.mkdir(parents=True, exist_ok=True)
    base = safe_filename_part(item_id, fallback="item", max_length=120)
    path = completed_dir / f"{base}.json"
    if not path.exists():
        return path

    counter = 2
    while True:
        candidate = completed_dir / f"{base}_{counter}.json"
        if not candidate.exists():
            return candidate
        counter += 1


def _resolve_date(value: Any, fallback: Any = "") -> str:
    if value is None:
        return parse_iso_date(str(fallback or "").strip()) or ""

    text = str(value or "").strip()
    if not text:
        return ""
    parsed = parse_iso_date(text)
    if not parsed:
        raise ValueError(f"Document date must use YYYY-MM-DD format: {text}")
    return parsed


def _resolve_text(value: Any, fallback: Any = "") -> str:
    if value is None:
        return str(fallback or "").strip()
    return str(value).strip()
