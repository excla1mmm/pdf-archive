from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


def json_sidecar_path(pdf_path: Path) -> Path:
    return _sidecar_path(pdf_path, ".json")


def xml_sidecar_path(pdf_path: Path) -> Path:
    return _sidecar_path(pdf_path, ".xml")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_xml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    root = ElementTree.Element("document")
    _append_value(root, payload)
    tree = ElementTree.ElementTree(root)
    ElementTree.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _append_value(parent: ElementTree.Element, value: Any, name: str | None = None) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = ElementTree.SubElement(parent, _xml_name(str(key)))
            _append_value(child, item)
    elif isinstance(value, list):
        for item in value:
            child = ElementTree.SubElement(parent, _xml_name(name or "item"))
            _append_value(child, item)
    else:
        parent.text = "" if value is None else str(value)


def _xml_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)
    if not safe or safe[0].isdigit():
        safe = f"field_{safe}"
    return safe


def _sidecar_path(pdf_path: Path, suffix: str) -> Path:
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    if pdf_path.suffix:
        return pdf_path.with_suffix(pdf_path.suffix + suffix)
    return pdf_path.with_suffix(suffix)
