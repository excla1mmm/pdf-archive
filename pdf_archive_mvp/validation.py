from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import AppConfig
from .utils import parse_iso_date


def choose_document_date(config: AppConfig, llm_date: str | None, date_candidates: list[str]) -> tuple[str | None, dict[str, Any]]:
    valid_candidates = [candidate for candidate in date_candidates if is_year_allowed(config, candidate)]
    parsed_llm_date = parse_iso_date(llm_date)
    llm_date_allowed = parsed_llm_date if parsed_llm_date and is_year_allowed(config, parsed_llm_date) else None
    warnings: list[str] = []
    source = "none"
    supported_by_text = False

    if llm_date_allowed and llm_date_allowed in valid_candidates:
        document_date = llm_date_allowed
        source = "llm"
        supported_by_text = True
    elif llm_date_allowed and not valid_candidates and not config.require_date_in_text:
        document_date = llm_date_allowed
        source = "llm_unverified"
        warnings.append("LLM date accepted without extracted date support.")
    elif valid_candidates:
        document_date = valid_candidates[0]
        source = "text_candidate"
        supported_by_text = True
        if parsed_llm_date and parsed_llm_date != document_date:
            warnings.append(f"LLM date {parsed_llm_date} was not supported by extracted date candidates.")
    else:
        document_date = None
        if parsed_llm_date and not llm_date_allowed:
            warnings.append(f"LLM date {parsed_llm_date} is outside the allowed year range.")
        elif parsed_llm_date and config.require_date_in_text:
            warnings.append(f"LLM date {parsed_llm_date} was rejected because no extracted date candidate supports it.")

    return document_date, {
        "source": source,
        "llm_date": parsed_llm_date or "",
        "date_candidates": date_candidates,
        "valid_date_candidates": valid_candidates,
        "supported_by_text": supported_by_text,
        "warnings": warnings,
    }


def build_review_reasons(
    config: AppConfig,
    classification: dict[str, Any],
    document_date: str | None,
    primary_barcode: str,
    archive_code: str,
    source_type: str,
    date_validation: dict[str, Any],
    has_enough_text_for_llm: bool,
) -> list[str]:
    reasons: list[str] = []
    if classification["confidence"] < config.confidence_review_threshold:
        reasons.append("low_confidence")
    if not document_date:
        reasons.append("missing_or_unverified_date")
    if date_validation.get("warnings"):
        reasons.append("date_validation_warning")
    if source_type == "paper_scan" and config.archive_code.require_barcode_for_paper and not primary_barcode:
        reasons.append("missing_barcode")
    if not archive_code:
        reasons.append("missing_archive_code")
    if classification["category_source"] == "ai_created":
        reasons.append("ai_created_category")
    if not has_enough_text_for_llm:
        reasons.append("insufficient_text")
    if classification.get("llm_unavailable") and not classification.get("fallback_strong_match"):
        reasons.append("llm_unavailable")
    return reasons


def is_year_allowed(config: AppConfig, iso_date: str) -> bool:
    parsed = parse_iso_date(iso_date)
    if not parsed:
        return False
    year = int(parsed[:4])
    max_year = datetime.now().year + config.max_future_years
    return config.min_document_year <= year <= max_year
