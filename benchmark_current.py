"""
Прогон текущей реализации (pdf_text.extract_pdf_text) на test_pdf/
и сравнение результатов с бенчмарком 7 экстракторов.

Не перемещает файлы — только классифицирует и выдаёт статистику.
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Загрузка модулей из .pyc (исходники отсутствуют) ──
def _load_pyc(name: str):
    pyc = Path(__file__).parent / "__pycache__" / f"{name}.cpython-311.pyc"
    spec = importlib.util.spec_from_file_location(name, str(pyc))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_load_pyc("text_rules")
pdf_text_mod = _load_pyc("pdf_text")

extract_pdf_text = pdf_text_mod.extract_pdf_text
PDFBlockedError = pdf_text_mod.PDFBlockedError
PDFOpenError = pdf_text_mod.PDFOpenError

from config import wordList, wordListMusor
from text_rules import prepare_needles, contains_any_prepared

# ── Настройки ──
TEST_DIR = Path(__file__).parent / "test_pdf"

WORDS = prepare_needles(wordList)
WORDS_MUSOR = prepare_needles(wordListMusor)

LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
DIGIT_RE = re.compile(r"\d")

def _has_letter_and_digit(t: str) -> bool:
    return bool(LETTER_RE.search(t)) and bool(DIGIT_RE.search(t))


def _ground_truth(name: str) -> str:
    stem = name.rsplit("(", 1)[0].strip().lower() if "(" in name else name.rsplit(".", 1)[0].strip().lower()
    mapping = {
        "bill_pdf": "bill_pdf",
        "bill_musor": "bill_musor",
        "img_pdf": "img_pdf",
        "text(pdf)nokey": "text_nokey",
        "block": "block",
        "fileerror": "fileerror",
    }
    for prefix, cat in mapping.items():
        if stem.startswith(prefix):
            return cat
    return stem


def classify_current(pdf_path: Path) -> tuple[str, float]:
    """Классификация как в run_pdfs_multi.classify_one, но без перемещения."""
    t0 = time.perf_counter()
    try:
        text = extract_pdf_text(pdf_path)
    except PDFBlockedError:
        return "block", time.perf_counter() - t0
    except Exception:
        return "fileerror", time.perf_counter() - t0

    t_strip = (text or "").strip()

    if not t_strip or not _has_letter_and_digit(t_strip):
        return "img_pdf", time.perf_counter() - t0

    if contains_any_prepared(t_strip, WORDS_MUSOR):
        return "bill_musor", time.perf_counter() - t0

    if contains_any_prepared(t_strip, WORDS):
        return "bill_pdf", time.perf_counter() - t0

    return "text_nokey", time.perf_counter() - t0


def main():
    files = sorted(TEST_DIR.glob("*.pdf"))
    total = len(files)
    print(f"Текущая реализация (pdf_text.extract_pdf_text): {total} файлов")
    print(f"Логика: PyPDF2 -> fitz -> pdfminer (каскад с таймаутом)")
    print()

    results = []
    t_start = time.perf_counter()

    for i, fp in enumerate(files):
        gt = _ground_truth(fp.name)
        predicted, elapsed = classify_current(fp)
        match = "OK" if predicted == gt else "MISS"
        results.append({
            "file": fp.name,
            "ground_truth": gt,
            "predicted": predicted,
            "match": match,
            "time": elapsed,
        })
        if (i + 1) % 50 == 0 or (i + 1) == total:
            total_elapsed = time.perf_counter() - t_start
            speed = (i + 1) / total_elapsed
            eta = (total - i - 1) / speed if speed > 0 else 0
            print(f"  [{i+1}/{total}] {speed:.1f} файлов/с | ETA {int(eta)}с | {fp.name}")

    total_elapsed = time.perf_counter() - t_start
    print(f"\nГотово за {total_elapsed:.1f}с")

    # ── Общая точность ──
    ok_count = sum(1 for r in results if r["match"] == "OK")
    acc = ok_count / total * 100
    avg_time = sum(r["time"] for r in results) / total

    print(f"\n{'='*70}")
    print(f"РЕЗУЛЬТАТ ТЕКУЩЕЙ РЕАЛИЗАЦИИ (pdf_text cascade)")
    print(f"{'='*70}")
    print(f"  Общая точность: {ok_count}/{total} = {acc:.1f}%")
    print(f"  Среднее время:  {avg_time:.3f}с/файл")
    print(f"  Общее время:    {total_elapsed:.1f}с")

    # ── По категориям ──
    cats = sorted(set(r["ground_truth"] for r in results))
    print(f"\n  {'Категория':<15} {'OK':>5} {'MISS':>5} {'Точность':>9}")
    for cat in cats:
        cat_rows = [r for r in results if r["ground_truth"] == cat]
        n = len(cat_rows)
        cat_ok = sum(1 for r in cat_rows if r["match"] == "OK")
        print(f"  {cat:<15} {cat_ok:>5} {n-cat_ok:>5} {cat_ok/n*100:>8.1f}%")

    # ── Ошибки классификации ──
    misses = [r for r in results if r["match"] == "MISS"]
    if misses:
        print(f"\n  Ошибки классификации ({len(misses)} шт.):")
        conf = Counter()
        for r in misses:
            conf[(r["ground_truth"], r["predicted"])] += 1
        for (gt, pred), cnt in conf.most_common():
            print(f"    {gt:>15} -> {pred:<15} : {cnt}")

    # ── Сравнение с бенчмарком ──
    print(f"\n{'='*70}")
    print(f"СРАВНЕНИЕ С БЕНЧМАРКОМ 7 ЭКСТРАКТОРОВ")
    print(f"{'='*70}")
    print(f"  {'Экстрактор':<20} {'Точность':>9} {'Время/файл':>11} {'Общее':>8}")
    print(f"  {'-'*50}")
    # benchmark results from the run
    benchmark_data = [
        ("pdfminer",       91.4, 0.321, 161),
        ("pymupdf",        91.2, 0.032, 16),
        ("pymupdf_raw",    91.2, 0.038, 19),
        ("pdfparse_node",  87.0, 0.249, 125),
        ("pypdfium2",      71.7, 0.013, 7),
        ("pdfplumber",     71.3, 0.425, 213),
        ("pypdf2",         69.3, 0.135, 68),
    ]
    # Insert current result
    all_results = benchmark_data + [("ТЕКУЩИЙ (каскад)", acc, avg_time, total_elapsed)]
    all_results.sort(key=lambda x: (-x[1], x[2]))

    for name, a, t, tt in all_results:
        marker = " <-- ВАШ КОД" if "ТЕКУЩИЙ" in name else ""
        print(f"  {name:<20} {a:>8.1f}% {t:>10.3f}с {tt:>7.0f}с{marker}")


if __name__ == "__main__":
    main()
