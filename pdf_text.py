# pdf_text.py — извлечение текста из PDF через PyMuPDF (fitz)
#
# Один экстрактор: fitz с sort=True (MuPDF C-движок).
# Без каскада, без подпроцессов — быстро и надёжно.
#
# Бенчмарк на 501 файле:
#   pymupdf sort=True  → 91.2% точность, 0.032с/файл
#   старый каскад      → 84.8% точность, 2.481с/файл
from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz

from config import MAX_PAGES_FOR_TEXT


class PDFOpenError(Exception):
    """Не удалось открыть PDF."""

class PDFBlockedError(Exception):
    """PDF защищён паролем (зашифрован)."""


def extract_pdf_text(fp: Path, max_pages: Optional[int] = None) -> str:
    """
    Извлекает текст из PDF файла через PyMuPDF (fitz).

    Args:
        fp: путь к PDF файлу
        max_pages: максимум страниц (по умолчанию из config.MAX_PAGES_FOR_TEXT)

    Returns:
        Текст из PDF (может быть пустым для сканов/изображений)

    Raises:
        PDFBlockedError: PDF зашифрован
        PDFOpenError: не удалось открыть файл
    """
    if max_pages is None:
        max_pages = MAX_PAGES_FOR_TEXT

    try:
        doc = fitz.open(str(fp))
    except Exception as e:
        raise PDFOpenError(f"{fp.name}: {e}") from e

    try:
        if doc.is_encrypted:
            raise PDFBlockedError(f"{fp.name}: encrypted")

        pages = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pages.append(page.get_text("text", sort=True))

        return "\n".join(pages)
    finally:
        doc.close()
