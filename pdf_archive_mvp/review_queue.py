from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .naming import build_filename, resolve_manual_category
from .pdf_tools import write_pdf_with_metadata
from .sidecar import write_json, write_xml
from .utils import now_iso, parse_iso_date, safe_filename_part, unique_path


@dataclass(frozen=True)
class QueuedItem:
    item_id: str
    pdf_path: Path
    draft_json_path: Path


def queue_root(config: AppConfig) -> Path:
    return config.archive_dir / "_Queue"


def queue_db_path(config: AppConfig) -> Path:
    return queue_root(config) / "review_queue.sqlite3"


def init_review_queue(config: AppConfig) -> None:
    root = queue_root(config)
    root.mkdir(parents=True, exist_ok=True)
    (root / "pending").mkdir(parents=True, exist_ok=True)
    (root / "drafts").mkdir(parents=True, exist_ok=True)
    with _connect(config) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_queue (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                original_path TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                pdf_path TEXT NOT NULL,
                draft_json_path TEXT NOT NULL,
                final_pdf_path TEXT,
                data_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status)")


def enqueue_review_item(config: AppConfig, source_pdf: Path, payload: dict[str, Any]) -> QueuedItem:
    init_review_queue(config)
    item_id = str(payload["archive_id"])
    queued_at = now_iso()
    original_name = source_pdf.name
    base_name = safe_filename_part(source_pdf.stem, fallback="document", max_length=80)

    pending_pdf = unique_path(queue_root(config) / "pending" / f"{base_name}_{item_id[:8]}.pdf")
    draft_json = queue_root(config) / "drafts" / f"{item_id}.json"

    pending_pdf.parent.mkdir(parents=True, exist_ok=True)
    draft_json.parent.mkdir(parents=True, exist_ok=True)

    if config.delete_source_after_success:
        shutil.move(str(source_pdf), str(pending_pdf))
    else:
        shutil.copy2(source_pdf, pending_pdf)

    payload["queue"] = {
        "id": item_id,
        "status": "pending_review",
        "queued_at": queued_at,
        "updated_at": queued_at,
        "pdf_path": str(pending_pdf),
        "draft_json_path": str(draft_json),
    }
    payload["source"]["queued_from_path"] = str(source_pdf)
    payload["source"]["path"] = str(pending_pdf)
    payload["manual_review"] = {
        "approved": False,
        "approved_at": "",
        "overrides": {},
    }

    write_json(draft_json, payload)
    with _connect(config) as conn:
        conn.execute(
            """
            INSERT INTO review_queue (
                id, status, queued_at, updated_at, original_path, original_filename,
                pdf_path, draft_json_path, final_pdf_path, data_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                "pending_review",
                queued_at,
                queued_at,
                str(source_pdf),
                original_name,
                str(pending_pdf),
                str(draft_json),
                None,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return QueuedItem(item_id=item_id, pdf_path=pending_pdf, draft_json_path=draft_json)


def list_review_items(config: AppConfig, include_completed: bool = False) -> list[dict[str, Any]]:
    init_review_queue(config)
    sql = "SELECT * FROM review_queue"
    params: tuple[Any, ...] = ()
    if not include_completed:
        sql += " WHERE status = ?"
        params = ("pending_review",)
    sql += " ORDER BY queued_at ASC"

    with _connect(config) as conn:
        rows = conn.execute(sql, params).fetchall()

    return [_row_to_summary(row) for row in rows]


def review_queue_snapshot(config: AppConfig, include_completed: bool = False) -> dict[str, Any]:
    return {
        "queue_db": str(queue_db_path(config)),
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
    with _connect(config) as conn:
        row = conn.execute("SELECT * FROM review_queue WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ValueError(f"Review queue item not found: {item_id}")
        if row["status"] != "pending_review":
            raise ValueError(f"Review queue item is not pending: {item_id} ({row['status']})")

    payload = _load_payload(row)
    pdf_path = Path(row["pdf_path"])
    if not pdf_path.exists():
        raise FileNotFoundError(f"Queued PDF not found: {pdf_path}")

    detected_before_review = {
        "barcode": payload.get("barcode", ""),
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
    filename = build_filename(document_date, category_folder, classification_for_filename, barcode)
    target_dir = config.archive_dir / target_year / category_folder
    target_pdf = unique_path(target_dir / filename)
    sidecar_base = target_pdf.with_suffix("")
    approved_at = now_iso()

    payload["detected_before_review"] = detected_before_review
    payload["barcode"] = barcode
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
    }
    payload["review_required"] = False
    payload["review_reasons"] = []
    payload["manual_review"] = {
        "approved": True,
        "approved_at": approved_at,
        "overrides": {
            "document_date": document_date,
            "barcode": barcode,
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
    }

    target_dir.mkdir(parents=True, exist_ok=True)
    metadata_written, metadata_error = write_pdf_with_metadata(
        pdf_path,
        target_pdf,
        {
            "Barcode": barcode,
            "ArchiveId": payload["archive_id"],
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

    write_json(sidecar_base.with_suffix(".json"), payload)
    if config.create_xml:
        write_xml(sidecar_base.with_suffix(".xml"), payload)

    draft_json_path = Path(row["draft_json_path"])
    write_json(draft_json_path, payload)
    if pdf_path.resolve() != target_pdf.resolve() and pdf_path.exists():
        pdf_path.unlink()

    with _connect(config) as conn:
        conn.execute(
            """
            UPDATE review_queue
            SET status = ?, updated_at = ?, final_pdf_path = ?, data_json = ?
            WHERE id = ?
            """,
            (
                "approved",
                approved_at,
                str(target_pdf),
                json.dumps(payload, ensure_ascii=False),
                item_id,
            ),
        )

    return {
        "id": item_id,
        "status": "approved",
        "target_pdf": str(target_pdf),
        "json": str(sidecar_base.with_suffix(".json")),
        "xml": str(sidecar_base.with_suffix(".xml")) if config.create_xml else "",
        "pdf_metadata_written": metadata_written,
    }


def _connect(config: AppConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(queue_db_path(config))
    conn.row_factory = sqlite3.Row
    return conn


def _load_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        draft_path = Path(row["draft_json_path"])
        if draft_path.exists():
            return json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return json.loads(row["data_json"])


def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
    payload = _load_payload(row)
    category = payload.get("category", {})
    target = payload.get("target", {})
    return {
        "id": row["id"],
        "status": row["status"],
        "queued_at": row["queued_at"],
        "updated_at": row["updated_at"],
        "original_filename": row["original_filename"],
        "pdf_path": row["pdf_path"],
        "draft_json_path": row["draft_json_path"],
        "final_pdf_path": row["final_pdf_path"] or "",
        "document_date": payload.get("document_date", ""),
        "barcode": payload.get("barcode", ""),
        "category_id": category.get("id", ""),
        "category_name": category.get("name", ""),
        "category_folder": category.get("folder", ""),
        "sender": payload.get("sender", ""),
        "title": payload.get("title", ""),
        "short_filename_title": payload.get("short_filename_title", ""),
        "confidence": payload.get("confidence", 0.0),
        "review_required": payload.get("review_required", True),
        "review_reasons": payload.get("review_reasons", []),
        "proposed_filename": target.get("filename", ""),
        "text_excerpt": payload.get("text_excerpt", ""),
    }


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
