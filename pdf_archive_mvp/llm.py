from __future__ import annotations

import json
from typing import Any

from .config import AppConfig, Category
from .utils import compact_whitespace, normalize_confidence, safe_filename_part, truncate_text


CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_date": {
            "type": "string",
            "description": "Document date as YYYY-MM-DD. Empty string if unknown.",
        },
        "category_id": {
            "type": "string",
            "description": "One fixed category id, or a new snake_case id if category_source is ai_created.",
        },
        "category_name": {"type": "string"},
        "category_source": {
            "type": "string",
            "enum": ["fixed", "ai_created"],
        },
        "new_category_suggestion": {
            "type": "string",
            "description": "Empty for fixed categories; human readable name for ai_created.",
        },
        "sender": {"type": "string"},
        "title": {"type": "string"},
        "short_filename_title": {
            "type": "string",
            "description": "Short file-safe title, max 60 chars, no date, no barcode.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "reasoning": {
            "type": "string",
            "description": "One short reason for the classification.",
        },
    },
    "required": [
        "document_date",
        "category_id",
        "category_name",
        "category_source",
        "new_category_suggestion",
        "sender",
        "title",
        "short_filename_title",
        "confidence",
        "reasoning",
    ],
}


def classify_with_ollama(
    config: AppConfig,
    text: str,
    barcode: str | None,
    date_candidates: list[str],
) -> dict[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is not installed. Run: pip install -r requirements.txt") from exc

    categories_payload = [
        {
            "id": category.id,
            "name": category.name,
            "description": category.description,
            "keywords": category.keywords,
        }
        for category in config.categories
    ]

    system_prompt = (
        "You classify private PDF documents for a local archive. "
        "Return only JSON matching the schema. Prefer fixed categories. "
        "Create an ai_created category only when no fixed category fits. "
        "Use YYYY-MM-DD for dates. If unknown, use an empty string. "
        "Use the document language for sender/title when possible."
    )
    user_prompt = {
        "fixed_categories": categories_payload,
        "barcode": barcode or "",
        "date_candidates": date_candidates,
        "document_text": truncate_text(text, config.max_chars_for_llm),
    }

    payload = {
        "model": config.llm.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
        "format": CLASSIFICATION_SCHEMA,
        "stream": False,
        "options": {"temperature": config.llm.temperature},
    }

    response = requests.post(
        f"{config.llm.base_url}/api/chat",
        json=payload,
        timeout=config.llm.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    content = data.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("Ollama returned an empty message.")
    return json.loads(content)


def fallback_classification(config: AppConfig, text: str, date_candidates: list[str]) -> dict[str, Any]:
    text_lower = text.lower()
    scored: list[tuple[int, Category]] = []
    for category in config.categories:
        score = sum(1 for keyword in category.keywords if keyword and keyword in text_lower)
        scored.append((score, category))

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_category = scored[0]
    if best_score == 0:
        best_category = config.categories_by_id.get("other", config.categories[-1])
        confidence = 0.35
    else:
        confidence = min(0.88, 0.52 + best_score * 0.12)

    title = _fallback_title(text, best_category)
    return {
        "document_date": date_candidates[0] if date_candidates else "",
        "category_id": best_category.id,
        "category_name": best_category.name,
        "category_source": "fixed",
        "new_category_suggestion": "",
        "sender": "",
        "title": title,
        "short_filename_title": safe_filename_part(title, fallback="Dokument", max_length=60),
        "confidence": confidence,
        "reasoning": "Fallback keyword classification; local LLM was disabled or unavailable.",
    }


def normalize_classification(config: AppConfig, raw: dict[str, Any]) -> dict[str, Any]:
    result = dict(raw)
    result["document_date"] = compact_whitespace(str(result.get("document_date", "")))
    result["category_id"] = safe_filename_part(result.get("category_id", "other"), fallback="other", max_length=60).lower()
    result["category_name"] = compact_whitespace(str(result.get("category_name", "")))
    result["category_source"] = result.get("category_source") if result.get("category_source") in {"fixed", "ai_created"} else "fixed"
    result["new_category_suggestion"] = compact_whitespace(str(result.get("new_category_suggestion", "")))
    result["sender"] = compact_whitespace(str(result.get("sender", "")))
    result["title"] = compact_whitespace(str(result.get("title", ""))) or "Dokument"
    result["short_filename_title"] = safe_filename_part(result.get("short_filename_title") or result["title"], fallback="Dokument", max_length=60)
    result["confidence"] = normalize_confidence(result.get("confidence"), default=0.0)
    result["reasoning"] = compact_whitespace(str(result.get("reasoning", "")))

    if result["category_source"] == "fixed" and result["category_id"] not in config.categories_by_id:
        result["category_id"] = "other" if "other" in config.categories_by_id else config.categories[-1].id
        result["category_name"] = config.categories_by_id[result["category_id"]].name
        result["confidence"] = min(result["confidence"], 0.45)
        result["reasoning"] = (result["reasoning"] + " Invalid fixed category id normalized.").strip()

    if result["category_source"] == "ai_created" and not config.llm.allow_ai_categories:
        result["category_source"] = "fixed"
        result["category_id"] = "other" if "other" in config.categories_by_id else config.categories[-1].id
        result["category_name"] = config.categories_by_id[result["category_id"]].name
        result["new_category_suggestion"] = ""
        result["confidence"] = min(result["confidence"], 0.5)

    return result


def _fallback_title(text: str, category: Category) -> str:
    for line in text.splitlines():
        cleaned = compact_whitespace(line)
        if 8 <= len(cleaned) <= 90:
            return cleaned
    return category.folder
