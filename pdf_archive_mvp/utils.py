from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

WINDOWS_FORBIDDEN_CHARS = '<>:"/\\|?*'


def compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def safe_filename_part(value: Any, fallback: str = "unknown", max_length: int = 80) -> str:
    text = compact_whitespace(str(value or ""))
    text = "".join("_" if char in WINDOWS_FORBIDDEN_CHARS else char for char in text)
    text = "".join(char for char in text if unicodedata.category(char)[0] != "C")
    text = re.sub(r"[\s.]+$", "", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("._ ")
    if not text:
        text = fallback
    return text[:max_length].rstrip("._ ")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def normalize_confidence(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    match = re.fullmatch(r"((?:19|20)\d{2})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    try:
        parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return parsed.isoformat()


def find_date_candidates(text: str, limit: int = 10) -> list[str]:
    candidates: list[str] = []

    for year, month, day in re.findall(r"\b((?:19|20)\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b", text):
        try:
            candidates.append(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            pass

    for day, month, year in re.findall(r"\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.]((?:19|20)\d{2})\b", text):
        try:
            candidates.append(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            pass

    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
        if len(unique) >= limit:
            break
    return unique


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
