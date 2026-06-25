from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_xml(path: Path, payload: dict[str, Any]) -> None:
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
