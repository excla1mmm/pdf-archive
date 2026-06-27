from __future__ import annotations

from typing import Any

from .config import AppConfig
from .utils import safe_filename_part


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


def resolve_manual_category(config: AppConfig, category_id: str, category_name: str = "") -> tuple[str, dict[str, Any]]:
    category_id = (category_id or "").strip()
    category_name = (category_name or "").strip()

    if category_id in config.categories_by_id:
        category = config.categories_by_id[category_id]
        return safe_filename_part(category.folder, fallback=category.id), {
            "id": category.id,
            "name": category.name,
            "folder": category.folder,
            "source": "manual_fixed",
            "new_category_suggestion": "",
        }

    new_name = category_name or category_id or "Neue Kategorie"
    folder = safe_filename_part(new_name, fallback="Neue_Kategorie", max_length=60)
    manual_id = safe_filename_part(category_id or new_name, fallback=folder, max_length=60).lower()
    return folder, {
        "id": manual_id,
        "name": new_name,
        "folder": folder,
        "source": "manual_new",
        "new_category_suggestion": new_name,
    }


def build_filename(
    document_date: str | None,
    category_folder: str,
    classification: dict[str, Any],
    archive_code: str,
) -> str:
    date_part = document_date or "undated"
    parts = [
        safe_filename_part(date_part, fallback="undated", max_length=20),
        safe_filename_part(category_folder, fallback="Kategorie", max_length=40),
        safe_filename_part(classification.get("sender"), fallback="", max_length=40),
        safe_filename_part(classification.get("short_filename_title"), fallback="Dokument", max_length=60),
    ]
    if archive_code:
        parts.append(safe_filename_part(archive_code, fallback="", max_length=40))

    cleaned = [part for part in parts if part]
    filename = "_".join(cleaned)
    return safe_filename_part(filename, fallback="document", max_length=180) + ".pdf"
