# text_rules.py — Unicode-нормализация, поиск ключевых слов, извлечение дат
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, List, Optional, Tuple
from unicodedata import normalize


# ═══════════════════════════════════════════════════════════
#  Нормализация текста
# ═══════════════════════════════════════════════════════════

def norm_text(s: str) -> str:
    """NFC-нормализация + casefold (регистронезависимое сравнение)."""
    return normalize("NFC", s).casefold()


# ═══════════════════════════════════════════════════════════
#  Поиск ключевых слов
# ═══════════════════════════════════════════════════════════

def prepare_needles(needles) -> tuple[str, ...]:
    """Предварительная нормализация списка ключевых слов."""
    return tuple(norm_text(w) for w in needles)


def contains_any_prepared(text: str, needles_norm: tuple[str, ...]) -> bool:
    """Проверяет вхождение любого из нормализованных ключевых слов в текст."""
    t = norm_text(text)
    return any(w in t for w in needles_norm)


def contains_any(text: str, needles: Iterable[str]) -> bool:
    """Проверяет вхождение любого ключевого слова (ненормализованного)."""
    return contains_any_prepared(text, prepare_needles(needles))


# ═══════════════════════════════════════════════════════════
#  Извлечение дат / годов
# ═══════════════════════════════════════════════════════════

MONTH_NAME_EN = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
MONTH_NAME = MONTH_NAME_EN

# DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY
DATE_RE = re.compile(
    r"\b(0?[1-9]|[12]\d|3[01])([./-])(0?[1-9]|1[0-2])\2((?:\d{2}){1,2})\b"
)

# 15 March 2024
DMY_RE = re.compile(
    rf"\b([0-3]?\d)\s+{MONTH_NAME_EN}\s+(\d{{2,4}})\b", re.IGNORECASE
)

# March 15 2024
MDY_RE = re.compile(
    rf"\b{MONTH_NAME_EN}\s+([0-3]?\d)\s+(\d{{2,4}})\b", re.IGNORECASE
)

# January 2025
MY_RE = re.compile(
    rf"\b{MONTH_NAME_EN}\s+(\d{{2,4}})\b", re.IGNORECASE
)

# Год с контекстом (для extract_year_with_context)
YEAR_WITH_CONTEXT_RE = re.compile(r"(.{0,50})(\b(19|20)\d{2}\b)")

YEAR_CONTEXT_WEIGHTS = {
    "invoice date": 1.0, "invoice_date": 1.0,
    "bill date": 1.0, "statement date": 1.0,
    "date:": 0.95, "dated:": 0.95, "datum:": 0.95, "дата:": 0.95,
    "date du": 0.9, "fecha:": 0.9, "data:": 0.9,
    "payment date": 0.85, "due date": 0.85,
    "transaction date": 0.8, "issue date": 0.8,
    "billing period": 0.75, "period:": 0.7,
    "effective": 0.6, "valid": 0.5,
    "from": 0.4, "to": 0.4,
    "copyright": 0.1, "\u00a9": 0.1,
    "established": 0.1, "founded": 0.1, "since": 0.1,
    "born": 0.05, "birthday": 0.05,
}


def _to_full_year(s: str) -> int:
    """Преобразует строку года (2 или 4 цифры) в полный год."""
    if len(s) <= 2:
        y = int(s)
        return 2000 + y if y < 100 else y
    return int(s)


def extract_years(text: str, year_range: Tuple[int, int] = (1990, 2100)) -> List[int]:
    """Извлекает все года из текста (DD.MM.YYYY, DD/MM/YYYY, month name YYYY)."""
    lo, hi = year_range
    years: list[int] = []

    # DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY
    for m in DATE_RE.finditer(text):
        y = _to_full_year(m.group(4).strip())
        if lo <= y <= hi:
            years.append(y)

    # 15 March 2024 / March 15 2024 / January 2025
    for rx in (DMY_RE, MDY_RE, MY_RE):
        for m in rx.finditer(text):
            y = _to_full_year(m.group(m.lastindex).strip())
            if lo <= y <= hi:
                years.append(y)

    return years


def pick_year_for_folder(years: List[int]) -> Optional[int]:
    """Выбирает год для папки: самый частый, при ничье — самый новый."""
    if not years:
        return None
    counts = Counter(years)
    max_count = max(counts.values())
    top = [y for y, c in counts.items() if c == max_count]
    return max(top)


def extract_year_with_context(
    text: str,
    year_range: Tuple[int, int] = (2000, 2030),
) -> Optional[int]:
    """Извлекает год с учётом контекста (ключевые слова рядом с годом)."""
    lo, hi = year_range
    year_scores: dict[int, list[float]] = {}

    for match in YEAR_WITH_CONTEXT_RE.finditer(text):
        context = match.group(1).casefold()
        year_str = match.group(2)

        try:
            year = int(year_str)
        except ValueError:
            continue

        if not (lo <= year <= hi):
            continue

        score = 0.3  # базовый вес

        for keyword, weight in YEAR_CONTEXT_WEIGHTS.items():
            if keyword in context:
                score = max(score, weight)

        year_scores.setdefault(year, []).append(score)

    if not year_scores:
        # Фоллбэк: простое извлечение через extract_years
        simple_years = extract_years(text, year_range)
        return pick_year_for_folder(simple_years)

    best_year = None
    best_total = 0.0

    for year, scores in year_scores.items():
        total = sum(scores) / (len(scores) + 1) + 0.1
        if total > best_total:
            best_total = total
            best_year = year

    return best_year
