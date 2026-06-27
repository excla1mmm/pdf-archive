from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive_code import assign_archive_code, infer_source_type
from .config import AppConfig
from .llm import classify_with_ollama, fallback_classification, normalize_classification
from .naming import build_filename, resolve_category
from .pdf_tools import decode_barcodes, extract_text, write_pdf_with_metadata
from .review_queue import enqueue_review_item
from .sidecar import json_sidecar_path, write_json, write_xml, xml_sidecar_path
from .utils import (
    find_date_candidates,
    now_iso,
    truncate_text,
    unique_path,
)
from .validation import build_review_reasons, choose_document_date


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


def process_directory(
    config: AppConfig,
    dry_run: bool = False,
    no_llm: bool = False,
    queue_review: bool = False,
) -> list[ProcessResult]:
    config.input_dir.mkdir(parents=True, exist_ok=True)
    config.archive_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for pdf_path in iter_pdfs(config.input_dir, config.recursive_input):
        try:
            results.append(process_pdf(config, pdf_path, dry_run=dry_run, no_llm=no_llm, queue_review=queue_review))
        except Exception as exc:
            logging.exception("Failed to process %s", pdf_path)
            results.append(ProcessResult(pdf_path, None, "error", True, str(exc)))
    return results


def process_pdf(
    config: AppConfig,
    pdf_path: Path,
    dry_run: bool = False,
    no_llm: bool = False,
    queue_review: bool = False,
) -> ProcessResult:
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

    primary_barcode, ignored_barcodes = select_archive_barcode(barcodes)
    warnings.extend(ignored_barcodes)
    text, extraction, text_warnings = extract_text(
        pdf_path,
        min_chars_before_ocr=config.min_text_chars_before_ocr,
        max_pages=config.max_pages_for_text,
        ocr=config.ocr,
    )
    warnings.extend(text_warnings)
    date_candidates = find_date_candidates(text)
    has_enough_text_for_llm = len(text.strip()) >= config.min_text_chars_before_ocr

    llm_info: dict[str, Any] = {
        "provider": config.llm.provider,
        "model": config.llm.model,
        "used": False,
        "error": "",
    }
    if not has_enough_text_for_llm:
        raw_classification = insufficient_text_classification(config, pdf_path, date_candidates)
        llm_info["error"] = "LLM skipped because extracted text is too short."
        warnings.append("LLM skipped because extracted text is too short for reliable classification.")
    elif config.llm.enabled and not no_llm:
        try:
            raw_classification = classify_with_ollama(config, text, primary_barcode, date_candidates)
            llm_info["used"] = True
        except Exception as exc:
            raw_classification = fallback_classification(config, text, date_candidates, source_name=pdf_path.name)
            raw_classification["llm_unavailable"] = True
            llm_info["error"] = str(exc)
            warnings.append(f"LLM unavailable; fallback classification used: {exc}")
    else:
        raw_classification = fallback_classification(config, text, date_candidates, source_name=pdf_path.name)
        llm_info["error"] = "LLM disabled by config or CLI."

    classification = normalize_classification(config, raw_classification)
    document_date, date_validation = choose_document_date(config, classification.get("document_date"), date_candidates)
    warnings.extend(date_validation["warnings"])
    target_year = document_date[:4] if document_date else config.unknown_year_folder
    category_folder, category_payload = resolve_category(config, classification)
    source_type = infer_source_type(config, pdf_path, primary_barcode)
    archive_code_info = assign_archive_code(
        config,
        source_type,
        document_date,
        primary_barcode,
        commit=not dry_run,
    )
    archive_code = archive_code_info.code

    review_reasons = build_review_reasons(
        config,
        classification,
        document_date,
        primary_barcode,
        archive_code,
        archive_code_info.source_type,
        date_validation,
        has_enough_text_for_llm,
    )
    review_required = bool(review_reasons)
    if review_required:
        target_dir = config.archive_dir / target_year / config.review_folder / category_folder
    elif classification["category_source"] == "ai_created":
        target_dir = config.archive_dir / target_year / config.ai_new_folder / category_folder
    else:
        target_dir = config.archive_dir / target_year / category_folder

    filename = build_filename(document_date, category_folder, classification, archive_code)
    target_pdf = unique_path(target_dir / filename)
    target_json = json_sidecar_path(target_pdf)
    target_xml = xml_sidecar_path(target_pdf)

    payload = {
        "schema_version": "pdf-archive-mvp/v1",
        "archive_id": archive_id,
        "status": "analyzed",
        "processed_at": processed_at,
        "workflow": {
            "stage": "analysis",
            "status": "review_required" if review_required else "ready_for_archive",
            "metadata_storage": "json_sidecar",
        },
        "source": {
            "path": str(pdf_path),
            "original_filename": pdf_path.name,
        },
        "target": {
            "path": str(target_pdf),
            "year": target_year,
            "folder": str(target_dir),
            "filename": target_pdf.name,
            "json_sidecar": str(target_json),
            "xml_sidecar": str(target_xml) if config.create_xml else "",
        },
        "metadata_sidecar": {
            "format": "json",
            "path": str(target_json),
            "xml_path": str(target_xml) if config.create_xml else "",
            "role": "final_metadata",
        },
        "barcode": primary_barcode,
        "barcodes": barcodes,
        "archive_code": archive_code,
        "archive_code_info": archive_code_info.as_payload(),
        "source_type": archive_code_info.source_type,
        "physical_document": archive_code_info.physical_document,
        "document_date": document_date or "",
        "category": category_payload,
        "sender": classification["sender"],
        "title": classification["title"],
        "short_filename_title": classification["short_filename_title"],
        "confidence": classification["confidence"],
        "review_required": review_required,
        "review_reasons": review_reasons,
        "classification_reasoning": classification["reasoning"],
        "date_validation": date_validation,
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

    if queue_review:
        queued = enqueue_review_item(config, pdf_path, payload)
        logging.info("QUEUED_REVIEW %s -> %s", pdf_path, queued.pdf_path)
        return ProcessResult(
            pdf_path,
            queued.pdf_path,
            "queued_review",
            True,
            f"Queued for manual review: {queued.item_id}",
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    metadata_written, metadata_error = write_pdf_with_metadata(
        pdf_path,
        target_pdf,
        {
            "Barcode": primary_barcode,
            "ArchiveCode": archive_code,
            "ArchiveId": archive_id,
            "ArchiveSourceType": archive_code_info.source_type,
            "ArchivePhysicalDocument": str(archive_code_info.physical_document).lower(),
            "DocumentDate": document_date or "",
            "DocumentCategory": category_payload["id"],
            "DocumentCategoryName": category_payload["name"],
            "ArchiveReviewRequired": str(review_required).lower(),
            "ArchiveReviewReasons": ",".join(review_reasons),
            "ArchiveProcessedAt": processed_at,
        },
    )
    payload["pdf_metadata_written"] = metadata_written
    if metadata_error:
        payload["extraction"]["warnings"].append(f"PDF metadata write failed; original copied: {metadata_error}")

    status = "review" if review_required else "archived"
    payload["status"] = status
    payload["workflow"] = {
        "stage": "post_processing",
        "status": status,
        "metadata_storage": "json_sidecar",
    }

    write_json(target_json, payload)
    if config.create_xml:
        write_xml(target_xml, payload)

    if config.delete_source_after_success and pdf_path.resolve() != target_pdf.resolve():
        pdf_path.unlink()

    logging.info("%s -> %s", status.upper(), target_pdf)
    return ProcessResult(pdf_path, target_pdf, status, review_required, "Processed successfully.")


def insufficient_text_classification(config: AppConfig, pdf_path: Path, date_candidates: list[str]) -> dict[str, Any]:
    category = config.categories_by_id.get("other", config.categories[-1])
    return {
        "document_date": date_candidates[0] if date_candidates else "",
        "category_id": category.id,
        "category_name": category.name,
        "category_source": "fixed",
        "new_category_suggestion": "",
        "sender": "",
        "title": "Insufficient extracted text",
        "short_filename_title": pdf_path.stem,
        "confidence": 0.0,
        "reasoning": "The extracted text is too short for reliable classification; document requires review.",
    }


def select_archive_barcode(barcodes: list[dict[str, str]]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not barcodes:
        return "", warnings

    top_right = [barcode for barcode in barcodes if barcode.get("source") == "top_right_crop"]
    full_page = [barcode for barcode in barcodes if barcode.get("source") != "top_right_crop"]

    for barcode in top_right:
        text = _clean_barcode_text(barcode.get("text", ""))
        if _is_archive_barcode_text(text):
            return text, warnings
        warnings.append(f"Ignored unreadable top-right barcode candidate: {barcode.get('format', '')}")

    for barcode in full_page:
        text = _clean_barcode_text(barcode.get("text", ""))
        barcode_format = str(barcode.get("format", "")).casefold()
        if barcode_format in {"code 128", "code 39", "qr code"} and _is_archive_barcode_text(text):
            warnings.append("Archive barcode was found only by full-page fallback; verify during review.")
            return text, warnings
        warnings.append(f"Ignored non-archive full-page barcode candidate: {barcode.get('format', '')}")

    return "", warnings


def _clean_barcode_text(value: str) -> str:
    return str(value or "").strip()


def _is_archive_barcode_text(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+\- ]*", value))
