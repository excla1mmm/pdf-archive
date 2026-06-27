from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .config import AppConfig, Category
from .utils import compact_whitespace, normalize_confidence, safe_filename_part, truncate_text

FALLBACK_CATEGORY_SIGNALS: dict[str, dict[str, int]] = {
    "energy": {
        "stadtwerke": 6,
        "strom": 5,
        "stromkosten": 5,
        "gas": 4,
        "gasverbrauch": 4,
        "kwh": 5,
        "zaehler": 5,
        "zaehlernummer": 5,
        "arbeitspreis": 5,
        "grundpreis": 5,
        "netzentgelt": 5,
        "netzentgelte": 5,
        "verbrauch": 4,
        "vertragskonto": 4,
        "lieferadresse": 3,
        "energie": 4,
        "energiepartner": 4,
        "wasser": 3,
        "abschlag": 3,
    },
    "salary": {
        "gehaltsabrechnung": 7,
        "lohnabrechnung": 7,
        "entgeltabrechnung": 7,
        "verdienstabrechnung": 7,
        "lohnsteuer": 5,
        "steuerklasse": 5,
        "sozialversicherung": 5,
        "personalnummer": 5,
        "arbeitgeber": 4,
        "nettobezug": 4,
        "gesamtbrutto": 4,
        "auszahlungsbetrag": 4,
        "gehalt": 4,
        "lohn": 4,
    },
    "bank_statement": {
        "kontoauszug": 6,
        "kontostand": 5,
        "iban": 4,
        "bic": 4,
        "buchungstag": 4,
        "wertstellung": 4,
        "saldo": 4,
    },
    "medical": {
        "laborbericht": 6,
        "labor": 5,
        "arzt": 5,
        "praxis": 4,
        "diagnose": 5,
        "befund": 5,
        "rezept": 4,
        "behandlung": 4,
    },
    "invoice": {
        "rechnung": 5,
        "rechnungsnummer": 5,
        "rechnungsdatum": 5,
        "zahlbetrag": 4,
        "faellig": 4,
        "mwst": 4,
        "ust": 3,
        "betrag": 2,
    },
    "shopping": {
        "bestellung": 5,
        "lieferung": 5,
        "lieferschein": 5,
        "retour": 4,
        "amazon": 4,
        "ebay": 4,
        "paket": 3,
    },
    "insurance": {
        "versicherung": 5,
        "versicherungsnummer": 5,
        "police": 4,
        "beitrag": 3,
        "schaden": 4,
        "haftpflicht": 4,
    },
    "contract": {
        "vertrag": 5,
        "vereinbarung": 4,
        "kuendigung": 5,
        "laufzeit": 4,
        "agb": 3,
    },
    "tax": {
        "finanzamt": 6,
        "steuerbescheid": 6,
        "einkommensteuer": 5,
        "umsatzsteuer": 5,
        "steuernummer": 4,
        "bescheid": 2,
    },
    "pension": {
        "rentenversicherung": 6,
        "rentenbescheid": 6,
        "rente": 5,
        "pension": 5,
        "versicherungsverlauf": 4,
    },
    "real_estate": {
        "nebenkostenabrechnung": 6,
        "mietvertrag": 6,
        "miete": 5,
        "vermieter": 4,
        "wohnung": 4,
        "grundsteuer": 4,
    },
    "health_insurance": {
        "krankenkasse": 6,
        "krankenversicherung": 6,
        "versichertennummer": 5,
        "versichertenkarte": 4,
        "mitgliedsbescheinigung": 4,
        "gesundheitskarte": 4,
    },
    "government": {
        "behoerde": 5,
        "behorde": 5,
        "buergerbuero": 5,
        "stadtverwaltung": 5,
        "gemeinde": 4,
        "bescheid": 3,
        "antrag": 3,
    },
    "legal": {
        "rechtsanwalt": 6,
        "kanzlei": 6,
        "gericht": 5,
        "klage": 5,
        "aktenzeichen": 5,
        "frist": 4,
        "fristschreiben": 5,
    },
    "car": {
        "werkstatt": 6,
        "fahrzeug": 5,
        "kfz": 5,
        "kennzeichen": 4,
        "reifen": 4,
        "leasing": 4,
    },
    "telecom": {
        "telekom": 7,
        "vodafone": 7,
        "mobilfunk": 6,
        "telefon": 5,
        "internet": 5,
        "rufnummer": 4,
        "kundennummer": 2,
        "router": 4,
        "o2": 5,
    },
    "warranty": {
        "garantie": 6,
        "gewaehrleistung": 6,
        "reparatur": 5,
        "seriennummer": 4,
        "garantienachweis": 6,
    },
    "travel": {
        "reise": 5,
        "hotel": 5,
        "flug": 5,
        "ticket": 4,
        "buchung": 4,
        "boarding": 4,
        "buchungsnummer": 4,
    },
    "education": {
        "zertifikat": 6,
        "bescheinigung": 5,
        "schule": 5,
        "universitaet": 5,
        "kurs": 4,
        "bildung": 4,
    },
}

PREFIX_SIGNALS = {
    "energie",
    "lohn",
    "rechnung",
    "rente",
    "strom",
    "steuer",
    "vertrag",
    "zaehler",
}


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
        "Use only facts supported by the provided document text. "
        "Do not invent sender names, dates, invoice titles, or categories when OCR text is weak. "
        "If the text is ambiguous, choose the best fixed category with low confidence or use other. "
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


def fallback_classification(
    config: AppConfig,
    text: str,
    date_candidates: list[str],
    source_name: str = "",
) -> dict[str, Any]:
    text_match = _normalize_for_matching(text)
    source_match = _normalize_for_matching(source_name)
    scored: list[tuple[int, int, Category, list[str]]] = []
    for category in config.categories:
        score, matches = _fallback_score_category(category, text_match, source_match)
        scored.append((score, len(matches), category, matches))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, _, best_category, best_matches = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    score_margin = best_score - second_score
    if best_score == 0:
        best_category = config.categories_by_id.get("other", config.categories[-1])
        confidence = 0.30
        best_matches = []
        score_margin = 0
        strong_match = False
    else:
        confident_match = best_score >= 4 and score_margin >= 2
        strong_match = best_score >= 10 and score_margin >= 5
        if confident_match:
            confidence = min(0.95, 0.60 + best_score * 0.025 + score_margin * 0.035)
        else:
            confidence = min(0.72, 0.42 + best_score * 0.04 + max(score_margin, 0) * 0.03)

    title = _fallback_title(text, best_category)
    match_hint = ", ".join(best_matches[:6]) if best_matches else "no strong keyword matches"
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
        "reasoning": (
            "Fallback keyword classification; "
            f"best={best_category.id} score={best_score}, margin={score_margin}, matches={match_hint}."
        ),
        "fallback_score": best_score,
        "fallback_score_margin": score_margin,
        "fallback_strong_match": strong_match,
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

    if result["category_source"] == "ai_created" and result["category_id"] in config.categories_by_id:
        category = config.categories_by_id[result["category_id"]]
        result["category_source"] = "fixed"
        result["category_name"] = category.name
        result["new_category_suggestion"] = ""
        result["reasoning"] = (result["reasoning"] + " Existing fixed category id normalized.").strip()

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


def _fallback_score_category(category: Category, text: str, source_name: str) -> tuple[int, list[str]]:
    score = 0
    matches: list[str] = []
    seen: set[str] = set()

    for keyword in category.keywords:
        normalized = _normalize_for_matching(keyword)
        if normalized and _contains_signal(text, normalized):
            score += 1
            seen.add(normalized)
            matches.append(normalized)

    for signal, weight in FALLBACK_CATEGORY_SIGNALS.get(category.id, {}).items():
        normalized = _normalize_for_matching(signal)
        if not normalized:
            continue
        already_counted = normalized in seen
        if _contains_signal(text, normalized):
            score += weight if not already_counted else max(0, weight - 1)
            if not already_counted:
                matches.append(normalized)
        elif source_name and _contains_signal(source_name, normalized):
            score += max(1, min(2, weight // 2))
            matches.append(f"filename:{normalized}")

    return score, matches


def _contains_signal(haystack: str, signal: str) -> bool:
    if not haystack or not signal:
        return False
    if " " in signal:
        return signal in haystack
    if signal in PREFIX_SIGNALS:
        return re.search(rf"\b{re.escape(signal)}[a-z0-9]*\b", haystack) is not None
    return re.search(rf"\b{re.escape(signal)}\b", haystack) is not None


def _normalize_for_matching(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = (
        normalized.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    normalized = re.sub(r"[_\-./\\]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()
