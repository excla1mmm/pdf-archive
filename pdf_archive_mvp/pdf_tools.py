from __future__ import annotations

import shutil
import re
import os
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


def _pil_resampling() -> Any:
    try:
        from PIL import Image

        return Image.Resampling.LANCZOS
    except AttributeError:
        return 1


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

    configure_tesseract_runtime(pytesseract)

    ocr_text: list[str] = []
    ocr_pages: list[dict[str, Any]] = []
    try:
        for page_index in range(len(pages_text)):
            image = render_page(pdf_path, page_index, ocr.dpi)
            prepared, page_info = prepare_ocr_image(image, ocr, pytesseract)
            text = pytesseract.image_to_string(prepared, lang=ocr.languages, config=ocr.tesseract_config)
            page_info["text_length"] = len(text.strip())
            ocr_pages.append(page_info)
            ocr_text.append(text)
    except Exception as exc:
        warnings.append(f"OCR failed: {exc}")
        return direct_text, {"method": "pdf_text", "pages": len(pages_text), "ocr_used": False}, warnings

    merged = "\n".join(ocr_text).strip()
    if not merged:
        warnings.append("OCR produced no text.")
        return direct_text, {"method": "pdf_text", "pages": len(pages_text), "ocr_used": False}, warnings

    return merged, {
        "method": "ocr",
        "pages": len(pages_text),
        "ocr_used": True,
        "ocr_languages": ocr.languages,
        "ocr_dpi": ocr.dpi,
        "tesseract_config": ocr.tesseract_config,
        "ocr_pages": ocr_pages,
    }, warnings


def configure_tesseract_runtime(pytesseract: Any) -> None:
    if shutil.which("tesseract"):
        return

    for candidate in _tesseract_candidates():
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            tessdata = candidate.parent / "tessdata"
            if tessdata.exists():
                os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
            return


def _tesseract_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "Tesseract-OCR" / "tesseract.exe")
    candidates.append(Path("C:/Program Files/Tesseract-OCR/tesseract.exe"))
    candidates.append(Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"))
    return candidates


def prepare_ocr_image(image: Any, ocr: OcrConfig, pytesseract: Any) -> tuple[Any, dict[str, Any]]:
    info: dict[str, Any] = {
        "preprocess_enabled": ocr.preprocess,
        "steps": [],
        "orientation_rotation": 0,
        "deskew_angle": 0.0,
    }
    if not ocr.preprocess:
        return image, info

    try:
        from PIL import ImageEnhance, ImageFilter, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is not installed. Run: pip install -r requirements.txt") from exc

    prepared = image.convert("RGB")

    if ocr.auto_rotate:
        rotation = detect_orientation_rotation(prepared, pytesseract)
        info["orientation_rotation"] = rotation
        if rotation:
            prepared = prepared.rotate(-rotation, expand=True, fillcolor="white")
            info["steps"].append(f"rotate:{rotation}")

    gray = ImageOps.grayscale(prepared)
    gray = ImageOps.autocontrast(gray)
    info["steps"].append("grayscale_autocontrast")

    if ocr.contrast and ocr.contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(ocr.contrast)
        info["steps"].append(f"contrast:{ocr.contrast:g}")

    if ocr.sharpness and ocr.sharpness != 1.0:
        gray = ImageEnhance.Sharpness(gray).enhance(ocr.sharpness)
        info["steps"].append(f"sharpness:{ocr.sharpness:g}")

    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    info["steps"].append("median_filter")

    if ocr.deskew:
        angle = estimate_skew_angle(gray, ocr.max_deskew_degrees)
        info["deskew_angle"] = round(angle, 2)
        if abs(angle) >= 0.25:
            gray = gray.rotate(-angle, expand=True, fillcolor=255)
            info["steps"].append(f"deskew:{angle:.2f}")

    if ocr.threshold is not None:
        threshold = max(0, min(255, int(ocr.threshold)))
        gray = gray.point(lambda pixel: 255 if pixel > threshold else 0)
        info["steps"].append(f"threshold:{threshold}")

    return gray, info


def detect_orientation_rotation(image: Any, pytesseract: Any) -> int:
    try:
        osd = pytesseract.image_to_osd(image)
    except Exception:
        return 0

    match = re.search(r"Rotate:\s+(\d+)", osd)
    if not match:
        return 0
    rotation = int(match.group(1)) % 360
    return rotation if rotation in {90, 180, 270} else 0


def estimate_skew_angle(image: Any, max_degrees: float) -> float:
    if max_degrees <= 0:
        return 0.0

    working = image.convert("L")
    max_width = 900
    if working.width > max_width:
        ratio = max_width / working.width
        new_size = (max_width, max(1, int(working.height * ratio)))
        working = working.resize(new_size, _pil_resampling())

    binary = working.point(lambda pixel: 0 if pixel < 180 else 255)
    if _dark_pixel_count(binary) < 100:
        return 0.0

    best_angle = 0.0
    best_score = _horizontal_projection_score(binary)
    steps = int(max_degrees / 0.5)
    for index in range(-steps, steps + 1):
        angle = index * 0.5
        if angle == 0:
            continue
        rotated = binary.rotate(angle, expand=True, fillcolor=255)
        score = _horizontal_projection_score(rotated)
        if score > best_score:
            best_score = score
            best_angle = angle
    return best_angle


def _dark_pixel_count(image: Any) -> int:
    return sum(1 for pixel in image.tobytes() if pixel < 128)


def _horizontal_projection_score(image: Any) -> float:
    width, height = image.size
    data = image.tobytes()
    rows = [data[start:start + width].count(0) for start in range(0, len(data), width)]
    if not rows:
        return 0.0
    mean = sum(rows) / height
    return sum((row - mean) ** 2 for row in rows) / height


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
