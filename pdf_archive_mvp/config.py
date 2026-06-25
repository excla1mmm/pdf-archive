from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    folder: str
    description: str
    keywords: list[str]


@dataclass(frozen=True)
class BarcodeConfig:
    left_ratio: float
    top_ratio: float
    width_ratio: float
    height_ratio: float
    dpi_crop: int
    dpi_full_page_fallback: int


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool
    languages: str
    dpi: int
    tesseract_config: str
    preprocess: bool
    auto_rotate: bool
    deskew: bool
    max_deskew_degrees: float
    contrast: float
    sharpness: float
    threshold: int | None


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool
    provider: str
    base_url: str
    model: str
    temperature: float
    timeout_seconds: int
    allow_ai_categories: bool


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    input_dir: Path
    archive_dir: Path
    review_folder: str
    ai_new_folder: str
    unknown_year_folder: str
    create_xml: bool
    include_extracted_text: bool
    recursive_input: bool
    delete_source_after_success: bool
    confidence_review_threshold: float
    min_text_chars_before_ocr: int
    min_document_year: int
    max_future_years: int
    require_date_in_text: bool
    max_pages_for_text: int
    max_chars_for_llm: int
    barcode: BarcodeConfig
    ocr: OcrConfig
    llm: LlmConfig
    categories: list[Category]

    @property
    def categories_by_id(self) -> dict[str, Category]:
        return {category.id: category for category in self.categories}


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _require_mapping(data: Any, name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"Config section '{name}' must be a mapping.")
    return data


def load_config(path: str | Path, input_override: str | None = None, archive_override: str | None = None) -> AppConfig:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is not installed. Run: pip install -r requirements.txt") from exc

    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    settings = _require_mapping(raw.get("settings", {}), "settings")
    barcode = _require_mapping(raw.get("barcode", {}), "barcode")
    ocr = _require_mapping(raw.get("ocr", {}), "ocr")
    llm = _require_mapping(raw.get("llm", {}), "llm")

    base_dir = config_path.parent
    input_dir = _resolve_path(input_override or settings.get("input_dir", "Input"), base_dir)
    archive_dir = _resolve_path(archive_override or settings.get("archive_dir", "Archive"), base_dir)

    categories = [
        Category(
            id=str(item["id"]),
            name=str(item["name"]),
            folder=str(item.get("folder") or item["id"]),
            description=str(item.get("description", "")),
            keywords=[str(keyword).lower() for keyword in item.get("keywords", [])],
        )
        for item in raw.get("categories", [])
    ]
    if not categories:
        raise ValueError("Config must define at least one category.")

    return AppConfig(
        config_path=config_path,
        input_dir=input_dir,
        archive_dir=archive_dir,
        review_folder=str(settings.get("review_folder", "_Review")),
        ai_new_folder=str(settings.get("ai_new_folder", "_AI_New")),
        unknown_year_folder=str(settings.get("unknown_year_folder", "UnknownYear")),
        create_xml=bool(settings.get("create_xml", True)),
        include_extracted_text=bool(settings.get("include_extracted_text", False)),
        recursive_input=bool(settings.get("recursive_input", False)),
        delete_source_after_success=bool(settings.get("delete_source_after_success", True)),
        confidence_review_threshold=float(settings.get("confidence_review_threshold", 0.75)),
        min_text_chars_before_ocr=int(settings.get("min_text_chars_before_ocr", 80)),
        min_document_year=int(settings.get("min_document_year", 1990)),
        max_future_years=int(settings.get("max_future_years", 1)),
        require_date_in_text=bool(settings.get("require_date_in_text", True)),
        max_pages_for_text=int(settings.get("max_pages_for_text", 6)),
        max_chars_for_llm=int(settings.get("max_chars_for_llm", 14000)),
        barcode=BarcodeConfig(
            left_ratio=float(barcode.get("left_ratio", 0.56)),
            top_ratio=float(barcode.get("top_ratio", 0.0)),
            width_ratio=float(barcode.get("width_ratio", 0.44)),
            height_ratio=float(barcode.get("height_ratio", 0.30)),
            dpi_crop=int(barcode.get("dpi_crop", 350)),
            dpi_full_page_fallback=int(barcode.get("dpi_full_page_fallback", 220)),
        ),
        ocr=OcrConfig(
            enabled=bool(ocr.get("enabled", True)),
            languages=str(ocr.get("languages", "deu+eng")),
            dpi=int(ocr.get("dpi", 260)),
            tesseract_config=str(ocr.get("tesseract_config", "--oem 1 --psm 6")),
            preprocess=bool(ocr.get("preprocess", True)),
            auto_rotate=bool(ocr.get("auto_rotate", True)),
            deskew=bool(ocr.get("deskew", True)),
            max_deskew_degrees=float(ocr.get("max_deskew_degrees", 4.0)),
            contrast=float(ocr.get("contrast", 1.35)),
            sharpness=float(ocr.get("sharpness", 1.15)),
            threshold=int(ocr["threshold"]) if ocr.get("threshold") is not None else None,
        ),
        llm=LlmConfig(
            enabled=bool(llm.get("enabled", True)),
            provider=str(llm.get("provider", "ollama")),
            base_url=str(llm.get("base_url", "http://localhost:11434")).rstrip("/"),
            model=str(llm.get("model", "gemma3:4b")),
            temperature=float(llm.get("temperature", 0.1)),
            timeout_seconds=int(llm.get("timeout_seconds", 180)),
            allow_ai_categories=bool(llm.get("allow_ai_categories", True)),
        ),
        categories=categories,
    )
