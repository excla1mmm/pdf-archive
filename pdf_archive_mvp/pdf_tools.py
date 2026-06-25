from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .config import BarcodeConfig, OcrConfig


def _import_fitz():
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is not installed. Run: pip install -r requirements.txt") from exc
    return fitz


def _pixmap_to_image(pix: Any):
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is not installed. Run: pip install -r requirements.txt") from exc

    mode = "RGB" if pix.alpha == 0 else "RGBA"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def render_first_page_crop(pdf_path: Path, barcode: BarcodeConfig):
    fitz = _import_fitz()
    with fitz.open(pdf_path) as doc:
        if doc.page_count == 0:
            raise RuntimeError("PDF has no pages.")
        page = doc.load_page(0)
        rect = page.rect
        clip = fitz.Rect(
            rect.x0 + rect.width * barcode.left_ratio,
            rect.y0 + rect.height * barcode.top_ratio,
            rect.x0 + rect.width * min(1.0, barcode.left_ratio + barcode.width_ratio),
            rect.y0 + rect.height * min(1.0, barcode.top_ratio + barcode.height_ratio),
        )
        zoom = barcode.dpi_crop / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        return _pixmap_to_image(pix)


def render_page(pdf_path: Path, page_index: int, dpi: int):
    fitz = _import_fitz()
    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_index)
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return _pixmap_to_image(pix)


def decode_barcodes(pdf_path: Path, barcode: BarcodeConfig) -> tuple[list[dict[str, str]], list[str]]:
    warnings: list[str] = []
    try:
        import zxingcpp
    except ImportError as exc:
        raise RuntimeError("zxing-cpp is not installed. Run: pip install -r requirements.txt") from exc

    found = []
    crop = render_first_page_crop(pdf_path, barcode)
    for result in zxingcpp.read_barcodes(crop):
        found.append(_barcode_to_dict(result, "top_right_crop"))

    if found:
        return found, warnings

    warnings.append("No barcode found in top-right crop; tried full first page fallback.")
    full_page = render_page(pdf_path, 0, barcode.dpi_full_page_fallback)
    for result in zxingcpp.read_barcodes(full_page):
        found.append(_barcode_to_dict(result, "full_first_page"))
    return found, warnings


def _barcode_to_dict(result: Any, source: str) -> dict[str, str]:
    return {
        "text": str(getattr(result, "text", "")),
        "format": str(getattr(result, "format", "")),
        "source": source,
    }


def extract_text(pdf_path: Path, min_chars_before_ocr: int, max_pages: int, ocr: OcrConfig) -> tuple[str, dict[str, Any], list[str]]:
    fitz = _import_fitz()
    warnings: list[str] = []
    pages_text: list[str] = []

    with fitz.open(pdf_path) as doc:
        page_count = min(doc.page_count, max_pages)
        for page_index in range(page_count):
            pages_text.append(doc.load_page(page_index).get_text("text"))

    direct_text = "\n".join(pages_text).strip()
    if len(direct_text) >= min_chars_before_ocr or not ocr.enabled:
        return direct_text, {"method": "pdf_text", "pages": len(pages_text), "ocr_used": False}, warnings

    try:
        import pytesseract
    except ImportError:
        warnings.append("pytesseract is not installed; OCR skipped.")
        return direct_text, {"method": "pdf_text", "pages": len(pages_text), "ocr_used": False}, warnings

    ocr_text: list[str] = []
    try:
        for page_index in range(len(pages_text)):
            image = render_page(pdf_path, page_index, ocr.dpi)
            ocr_text.append(pytesseract.image_to_string(image, lang=ocr.languages))
    except Exception as exc:
        warnings.append(f"OCR failed: {exc}")
        return direct_text, {"method": "pdf_text", "pages": len(pages_text), "ocr_used": False}, warnings

    merged = "\n".join(ocr_text).strip()
    if not merged:
        warnings.append("OCR produced no text.")
        return direct_text, {"method": "pdf_text", "pages": len(pages_text), "ocr_used": False}, warnings

    return merged, {"method": "ocr", "pages": len(pages_text), "ocr_used": True}, warnings


def write_pdf_with_metadata(source: Path, target: Path, metadata: dict[str, str]) -> tuple[bool, str | None]:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError("pypdf is not installed. Run: pip install -r requirements.txt") from exc

    try:
        reader = PdfReader(str(source))
        if reader.is_encrypted:
            reader.decrypt("")

        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        current_metadata = {}
        if reader.metadata:
            current_metadata.update({str(key): str(value) for key, value in reader.metadata.items() if value is not None})
        current_metadata.update({f"/{key.lstrip('/')}": str(value) for key, value in metadata.items() if value is not None})
        writer.add_metadata(current_metadata)

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(target.suffix + ".tmp")
        with tmp_path.open("wb") as handle:
            writer.write(handle)
        tmp_path.replace(target)
        return True, None
    except Exception as exc:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return False, str(exc)
