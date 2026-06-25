from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig, Category
from .llm import classify_with_ollama, fallback_classification, normalize_classification
from .pdf_tools import decode_barcodes, extract_text, write_pdf_with_metadata
from .sidecar import write_json, write_xml
from .utils import (
    find_date_candidates,
    now_iso,
    parse_iso_date,
    safe_filename_part,
    truncate_text,
    unique_path,
)


@dataclass(frozen=True)
class ProcessResult:
    source: Path
    target: Path | None
    status: str
    review_required: bool
    message: str


def configure_logging(archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    log_path = archive_dir / "archive.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def iter_pdfs(input_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(path for path in input_dir.glob(pattern) if path.is_file())


def process_directory(config: AppConfig, dry_run: bool = False, no_llm: bool = False) -> list[ProcessResult]:
    config.input_dir.mkdir(parents=True, exist_ok=True)
    config.archive_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for pdf_path in iter_pdfs(config.input_dir, config.recursive_input):
        try:
            results.append(process_pdf(config, pdf_path, dry_run=dry_run, no_llm=no_llm))
        except Exception as exc:
            logging.exception("Failed to process %s", pdf_path)
            results.append(ProcessResult(pdf_path, None, "error", True, str(exc)))
    return results


def process_pdf(config: AppConfig, pdf_path: Path, dry_run: bool = False, no_llm: bool = False) -> ProcessResult:
    logging.info("Processing %s", pdf_path)
    processed_at = now_iso()
    archive_id = str(uuid.uuid4())
    warnings: list[str] = []

    barcodes = []
    try:
        barcodes, barcode_warnings = decode_barcodes(pdf_path, config.barcode)
        warnings.extend(barcode_warnings)
    except Exception as exc:
        warnings.append(f"Barcode detection failed: {exc}")

    primary_barcode = barcodes[0]["text"] if barcodes else ""
    text, extraction, text_warnings = extract_text(
        pdf_path,
        min_chars_before_ocr=config.min_text_chars_before_ocr,
        max_pages=config.max_pages_for_text,
        ocr=config.ocr,
    )
    warnings.extend(text_warnings)
    date_candidates = find_date_candidates(text)

    llm_info: dict[str, Any] = {
        "provider": config.llm.provider,
        "model": config.llm.model,
        "used": False,
        "error": "",
    }
    if config.llm.enabled and not no_llm:
        try:
            raw_classification = classify_with_ollama(config, text, primary_barcode, date_candidates)
            llm_info["used"] = True
        except Exception as exc:
            raw_classification = fallback_classification(config, text, date_candidates)
            llm_info["error"] = str(exc)
            warnings.append(f"LLM unavailable; fallback classification used: {exc}")
    else:
        raw_classification = fallback_classification(config, text, date_candidates)
        llm_info["error"] = "LLM disabled by config or CLI."

    classification = normalize_classification(config, raw_classification)
    document_date = parse_iso_date(classification.get("document_date")) or (date_candidates[0] if date_candidates else None)
    target_year = document_date[:4] if document_date else config.unknown_year_folder
    category_folder, category_payload = resolve_category(config, classification)

    review_required = (
        classification["confidence"] < config.confidence_review_threshold
        or not document_date
        or not primary_barcode
        or classification["category_source"] == "ai_created"
    )
    if review_required:
        target_dir = config.archive_dir / target_year / config.review_folder / category_folder
    elif classification["category_source"] == "ai_created":
        target_dir = config.archive_dir / target_year / config.ai_new_folder / category_folder
    else:
        target_dir = config.archive_dir / target_year / category_folder

    filename = build_filename(document_date, category_folder, classification, primary_barcode)
    target_pdf = unique_path(target_dir / filename)
    sidecar_base = target_pdf.with_suffix("")

    payload = {
        "schema_version": "pdf-archive-mvp/v1",
        "archive_id": archive_id,
        "processed_at": processed_at,
        "source": {
            "path": str(pdf_path),
            "original_filename": pdf_path.name,
        },
        "target": {
            "path": str(target_pdf),
            "year": target_year,
            "folder": str(target_dir),
            "filename": target_pdf.name,
        },
        "barcode": primary_barcode,
        "barcodes": barcodes,
        "document_date": document_date or "",
        "category": category_payload,
        "sender": classification["sender"],
        "title": classification["title"],
        "short_filename_title": classification["short_filename_title"],
        "confidence": classification["confidence"],
        "review_required": review_required,
        "classification_reasoning": classification["reasoning"],
        "extraction": {
            **extraction,
            "text_length": len(text),
            "date_candidates": date_candidates,
            "warnings": warnings,
        },
        "llm": llm_info,
        "text_excerpt": truncate_text(text, 2000),
    }
    if config.include_extracted_text:
        payload["extracted_text"] = text

    if dry_run:
        logging.info("Dry run target for %s: %s", pdf_path, target_pdf)
        return ProcessResult(pdf_path, target_pdf, "dry_run", review_required, "Planned only; no files were written.")

    target_dir.mkdir(parents=True, exist_ok=True)
    metadata_written, metadata_error = write_pdf_with_metadata(
        pdf_path,
        target_pdf,
        {
            "Barcode": primary_barcode,
            "ArchiveId": archive_id,
            "DocumentDate": document_date or "",
            "DocumentCategory": category_payload["id"],
            "DocumentCategoryName": category_payload["name"],
            "ArchiveProcessedAt": processed_at,
        },
    )
    payload["pdf_metadata_written"] = metadata_written
    if metadata_error:
        payload["extraction"]["warnings"].append(f"PDF metadata write failed; original copied: {metadata_error}")

    write_json(sidecar_base.with_suffix(".json"), payload)
    if config.create_xml:
        write_xml(sidecar_base.with_suffix(".xml"), payload)

    if config.delete_source_after_success and pdf_path.resolve() != target_pdf.resolve():
        pdf_path.unlink()

    status = "review" if review_required else "archived"
    logging.info("%s -> %s", status.upper(), target_pdf)
    return ProcessResult(pdf_path, target_pdf, status, review_required, "Processed successfully.")


def resolve_category(config: AppConfig, classification: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if classification["category_source"] == "fixed":
        category = config.categories_by_id[classification["category_id"]]
        return safe_filename_part(category.folder, fallback=category.id), {
            "id": category.id,
            "name": category.name,
            "folder": category.folder,
            "source": "fixed",
            "new_category_suggestion": "",
        }

    new_name = classification["new_category_suggestion"] or classification["category_name"] or classification["category_id"]
    folder = safe_filename_part(new_name, fallback=classification["category_id"], max_length=60)
    return folder, {
        "id": classification["category_id"],
        "name": new_name,
        "folder": folder,
        "source": "ai_created",
        "new_category_suggestion": new_name,
    }


def build_filename(
    document_date: str | None,
    category_folder: str,
    classification: dict[str, Any],
    barcode: str,
) -> str:
    date_part = document_date or "undated"
    parts = [
        safe_filename_part(date_part, fallback="undated", max_length=20),
        safe_filename_part(category_folder, fallback="Kategorie", max_length=40),
        safe_filename_part(classification.get("sender"), fallback="", max_length=40),
        safe_filename_part(classification.get("short_filename_title"), fallback="Dokument", max_length=60),
    ]
    if barcode:
        parts.append(safe_filename_part(barcode, fallback="", max_length=40))

    cleaned = [part for part in parts if part]
    filename = "_".join(cleaned)
    return safe_filename_part(filename, fallback="document", max_length=180) + ".pdf"
