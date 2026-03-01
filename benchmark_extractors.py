"""
Benchmark: сравнение 7 PDF-библиотек на извлечение текста.

Берёт файлы из test_pdf/, где имя файла = ground-truth категория от BAS (pdf-parse).
Прогоняет каждый файл через 7 экстракторов, сверяет с wordList/wordListMusor,
выдаёт CSV + сводную таблицу.

Экстракторы:
  1. PyMuPDF (fitz)        — C-движок MuPDF, get_text(sort=True)
  2. PyMuPDF-raw (fitz)    — MuPDF через rawdict → полный Unicode из spans
  3. PyPDF2                — pure-Python
  4. pdfminer.six          — pure-Python, layout analysis
  5. pdfplumber            — обёртка pdfminer + таблицы, x_tolerance=3
  6. pypdfium2             — Google PDFium (Chrome), get_text_bounded()
  7. pdf-parse (Node.js)   — Mozilla pdf.js

Запуск:
    python benchmark_extractors.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import time
import unicodedata

# Fix Windows console encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# ── Настройки ──────────────────────────────────────────────
TEST_DIR = Path(__file__).parent / "test_pdf"
OUT_CSV = Path(__file__).parent / "benchmark_results.csv"
OUT_SUMMARY = Path(__file__).parent / "benchmark_summary.txt"
NODE_SCRIPT = Path(__file__).parent / "_node_extract.js"
MAX_PAGES = 5          # сколько страниц анализировать
TIMEOUT_SEC = 30       # таймаут на один файл
# ───────────────────────────────────────────────────────────

from config import wordList, wordListMusor

def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()

WORDS_NORM = [_norm(w) for w in wordList]
WORDS_MUSOR_NORM = [_norm(w) for w in wordListMusor]

def _match_words(text: str) -> tuple[bool, bool]:
    """Возвращает (has_keyword, has_musor)."""
    if not text or not text.strip():
        return False, False
    t = _norm(text)
    has_kw = any(w in t for w in WORDS_NORM)
    has_musor = any(w in t for w in WORDS_MUSOR_NORM)
    return has_kw, has_musor

def _has_real_text(text: str) -> bool:
    """Есть ли реальный текст (буквы + цифры)."""
    if not text or not text.strip():
        return False
    import re
    has_letter = bool(re.search(r"[A-Za-zА-Яа-яЁё]", text))
    has_digit = bool(re.search(r"\d", text))
    return has_letter and has_digit


# ═══════════════════════════════════════════════════════════
#  Экстракторы
# ═══════════════════════════════════════════════════════════

def extract_pymupdf(fp: Path) -> str:
    """PyMuPDF (fitz) — MuPDF engine, sort=True для правильного порядка чтения."""
    import fitz
    doc = fitz.open(str(fp))
    if doc.is_encrypted:
        doc.close()
        raise PermissionError("encrypted")
    pages = []
    for i, page in enumerate(doc):
        if i >= MAX_PAGES:
            break
        # sort=True — сортировка блоков по reading order (top-to-bottom, left-to-right)
        # flags: TEXT_DEHYPHENATE (убрать переносы) + TEXT_PRESERVE_LIGATURES
        pages.append(page.get_text("text", sort=True))
    doc.close()
    return "\n".join(pages)


def extract_pymupdf_raw(fp: Path) -> str:
    """PyMuPDF rawdict — полный Unicode из chars, обход проблем CIDFont/ToUnicode."""
    import fitz
    doc = fitz.open(str(fp))
    if doc.is_encrypted:
        doc.close()
        raise PermissionError("encrypted")
    all_text = []
    for i, page in enumerate(doc):
        if i >= MAX_PAGES:
            break
        # rawdict → chars[].c содержит посимвольный Unicode текст
        data = page.get_text("rawdict", sort=True)
        page_lines = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:  # skip image blocks
                continue
            for line in block.get("lines", []):
                line_chars = []
                for span in line.get("spans", []):
                    chars = span.get("chars", [])
                    span_text = "".join(c.get("c", "") for c in chars)
                    if span_text.strip():
                        line_chars.append(span_text)
                if line_chars:
                    page_lines.append(" ".join(line_chars))
        all_text.append("\n".join(page_lines))
    doc.close()
    return "\n".join(all_text)


def extract_pypdf2(fp: Path) -> str:
    """PyPDF2 — pure-Python."""
    from PyPDF2 import PdfReader
    reader = PdfReader(str(fp))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise PermissionError("encrypted")
    pages = []
    for i, page in enumerate(reader.pages):
        if i >= MAX_PAGES:
            break
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def extract_pdfminer(fp: Path) -> str:
    """pdfminer.six — pure-Python, layout analysis."""
    from pdfminer.high_level import extract_text
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    try:
        return extract_text(str(fp), maxpages=MAX_PAGES)
    except PDFPasswordIncorrect:
        raise PermissionError("encrypted")


def extract_pdfplumber(fp: Path) -> str:
    """pdfplumber — обёртка над pdfminer, x_tolerance=3 для лучшего склеивания слов."""
    import pdfplumber
    pages = []
    with pdfplumber.open(str(fp)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= MAX_PAGES:
                break
            # x_tolerance=3 — расстояние между символами для объединения в слова
            # y_tolerance=3 — расстояние между строками
            t = page.extract_text(x_tolerance=3, y_tolerance=3)
            if t:
                pages.append(t)
    return "\n".join(pages)


def extract_pypdfium2(fp: Path) -> str:
    """pypdfium2 — Google PDFium (Chrome), get_text_bounded для полного Unicode."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(fp))
    pages = []
    for i in range(min(len(doc), MAX_PAGES)):
        page = doc[i]
        textpage = page.get_textpage()
        # get_text_bounded() — извлекает весь текст страницы с полной Unicode поддержкой
        # в отличие от get_text_range(), лучше обрабатывает CIDFont и сложные кодировки
        pages.append(textpage.get_text_bounded())
        textpage.close()
        page.close()
    doc.close()
    return "\n".join(pages)


# Node.js pdf-parse (вызов через subprocess)
_NODE_SCRIPT_CODE = r"""
const fs = require("fs");
const pdfParse = require("pdf-parse");

const filePath = process.argv[2];
const maxPages = parseInt(process.argv[3]) || 5;

const buf = fs.readFileSync(filePath);

const opts = {
    max: maxPages  // pdf-parse: max pages
};

pdfParse(buf, opts)
    .then(data => {
        // output as JSON
        process.stdout.write(JSON.stringify({
            ok: true,
            text: data.text,
            numpages: data.numpages,
            info: data.info || {}
        }));
    })
    .catch(err => {
        process.stdout.write(JSON.stringify({
            ok: false,
            error: err.message || String(err)
        }));
    });
"""

def _ensure_node_script():
    if not NODE_SCRIPT.exists():
        NODE_SCRIPT.write_text(_NODE_SCRIPT_CODE, encoding="utf-8")

def extract_pdfparse_node(fp: Path) -> str:
    """pdf-parse (Node.js / Mozilla pdf.js)."""
    _ensure_node_script()
    r = subprocess.run(
        ["node", str(NODE_SCRIPT), str(fp), str(MAX_PAGES)],
        capture_output=True, text=True, timeout=TIMEOUT_SEC,
        encoding="utf-8", errors="replace"
    )
    if r.returncode != 0:
        raise RuntimeError(f"node exit {r.returncode}: {r.stderr[:200]}")
    data = json.loads(r.stdout)
    if not data.get("ok"):
        err = data.get("error", "unknown")
        if "password" in err.lower() or "encrypt" in err.lower():
            raise PermissionError("encrypted")
        raise RuntimeError(err)
    return data["text"]


EXTRACTORS = {
    "pymupdf":        extract_pymupdf,
    "pymupdf_raw":    extract_pymupdf_raw,
    "pypdf2":         extract_pypdf2,
    "pdfminer":       extract_pdfminer,
    "pdfplumber":     extract_pdfplumber,
    "pypdfium2":      extract_pypdfium2,
    "pdfparse_node":  extract_pdfparse_node,
}


# ═══════════════════════════════════════════════════════════
#  Ground truth из имени файла
# ═══════════════════════════════════════════════════════════

def _ground_truth(name: str) -> str:
    """
    Извлекает категорию из имени файла:
      'bill_pdf (42).pdf'    -> 'bill_pdf'
      'bill_musor (5).pdf'   -> 'bill_musor'
      'img_pdf (10).pdf'     -> 'img_pdf'
      'text(pdf)nokey (7).pdf' -> 'text_nokey'
      'block (3).pdf'        -> 'block'
      'fileerror (1).pdf'    -> 'fileerror'
    """
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


# ═══════════════════════════════════════════════════════════
#  Классификация (повторяет логику run_pdfs_multi)
# ═══════════════════════════════════════════════════════════

def classify_text(text: str | None, was_error: bool = False, was_blocked: bool = False) -> str:
    """
    Классифицирует результат извлечения:
      'bill_pdf'    — есть ключевые слова wordList
      'bill_musor'  — есть мусорные слова (и нет ключевых, или есть оба)
      'text_nokey'  — есть текст, но нет ключевых слов
      'img_pdf'     — нет текста
      'block'       — зашифрован
      'fileerror'   — ошибка чтения
    """
    if was_blocked:
        return "block"
    if was_error:
        return "fileerror"
    if text is None or not text.strip():
        return "img_pdf"
    if not _has_real_text(text):
        return "img_pdf"

    has_kw, has_musor = _match_words(text)

    # Логика из run_pdfs_multi: musor проверяется ПЕРЕД keywords
    if has_musor:
        return "bill_musor"
    if has_kw:
        return "bill_pdf"
    return "text_nokey"


# ═══════════════════════════════════════════════════════════
#  Основной бенчмарк
# ═══════════════════════════════════════════════════════════

def process_one_file(pdf_path: Path) -> dict:
    gt = _ground_truth(pdf_path.name)
    row = {"file": pdf_path.name, "ground_truth": gt}

    for ext_name, ext_func in EXTRACTORS.items():
        t0 = time.perf_counter()
        text = None
        error = ""
        blocked = False
        try:
            text = ext_func(pdf_path)
        except PermissionError:
            blocked = True
        except subprocess.TimeoutExpired:
            error = "timeout"
        except Exception as e:
            error = type(e).__name__
        elapsed = time.perf_counter() - t0

        predicted = classify_text(text, was_error=bool(error), was_blocked=blocked)
        text_len = len(text) if text else 0
        has_kw, has_musor = _match_words(text) if text else (False, False)

        row[f"{ext_name}_class"] = predicted
        row[f"{ext_name}_match"] = "OK" if predicted == gt else "MISS"
        row[f"{ext_name}_textlen"] = text_len
        row[f"{ext_name}_has_kw"] = has_kw
        row[f"{ext_name}_has_musor"] = has_musor
        row[f"{ext_name}_error"] = error
        row[f"{ext_name}_time"] = round(elapsed, 3)

    return row


def run_benchmark():
    files = sorted(TEST_DIR.glob("*.pdf"))
    total = len(files)
    print(f"Benchmark: {total} files, {len(EXTRACTORS)} extractors")
    print(f"Extractors: {', '.join(EXTRACTORS.keys())}")
    print()

    _ensure_node_script()

    rows = []
    t_start = time.perf_counter()

    for i, fp in enumerate(files):
        row = process_one_file(fp)
        rows.append(row)
        if (i + 1) % 50 == 0 or (i + 1) == total:
            elapsed = time.perf_counter() - t_start
            speed = (i + 1) / elapsed
            eta = (total - i - 1) / speed if speed > 0 else 0
            print(f"  [{i+1}/{total}] {speed:.1f} files/s | ETA {int(eta)}s | last: {fp.name}")

    elapsed_total = time.perf_counter() - t_start
    print(f"\nDone in {elapsed_total:.1f}s")

    # ── Сохраняем CSV ──
    fieldnames = rows[0].keys() if rows else []
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"CSV saved: {OUT_CSV}")

    # ── Сводная таблица ──
    summary_lines = build_summary(rows)
    summary_text = "\n".join(summary_lines)
    OUT_SUMMARY.write_text(summary_text, encoding="utf-8")
    print(f"Summary saved: {OUT_SUMMARY}")
    print()
    print(summary_text)


def build_summary(rows: list[dict]) -> list[str]:
    lines = []
    ext_names = list(EXTRACTORS.keys())
    total = len(rows)
    cats = sorted(set(r["ground_truth"] for r in rows))

    lines.append("=" * 80)
    lines.append(f"BENCHMARK SUMMARY — {total} files")
    lines.append("=" * 80)

    # 1. Общая точность
    lines.append("")
    lines.append("1. OVERALL ACCURACY (match with ground truth)")
    lines.append("-" * 60)
    header = f"{'Extractor':<18}" + "".join(f"{'OK':>7} {'MISS':>6} {'Acc%':>7}" for _ in [""])
    # Better: one line per extractor
    lines.append(f"  {'Extractor':<18} {'OK':>6} {'MISS':>6} {'Accuracy':>8} {'Avg Time':>9}")
    for ext in ext_names:
        ok = sum(1 for r in rows if r[f"{ext}_match"] == "OK")
        miss = total - ok
        acc = ok / total * 100 if total else 0
        avg_t = sum(r[f"{ext}_time"] for r in rows) / total if total else 0
        lines.append(f"  {ext:<18} {ok:>6} {miss:>6} {acc:>7.1f}% {avg_t:>8.3f}s")

    # 2. Accuracy per category
    lines.append("")
    lines.append("2. ACCURACY PER CATEGORY")
    lines.append("-" * 60)
    for cat in cats:
        cat_rows = [r for r in rows if r["ground_truth"] == cat]
        n = len(cat_rows)
        lines.append(f"\n  [{cat}] ({n} files)")
        lines.append(f"  {'Extractor':<18} {'OK':>6} {'MISS':>6} {'Acc%':>7}")
        for ext in ext_names:
            ok = sum(1 for r in cat_rows if r[f"{ext}_match"] == "OK")
            acc = ok / n * 100 if n else 0
            lines.append(f"  {ext:<18} {ok:>6} {n-ok:>6} {acc:>7.1f}%")

    # 3. Confusion: what did each extractor predict for MISSed files
    lines.append("")
    lines.append("3. MISCLASSIFICATION DETAILS")
    lines.append("-" * 60)
    for ext in ext_names:
        misses = [r for r in rows if r[f"{ext}_match"] == "MISS"]
        if not misses:
            lines.append(f"  {ext}: 0 misses — PERFECT!")
            continue
        lines.append(f"\n  {ext} ({len(misses)} misses):")
        # group by gt -> predicted
        from collections import Counter
        conf = Counter()
        for r in misses:
            conf[(r["ground_truth"], r[f"{ext}_class"])] += 1
        for (gt, pred), cnt in conf.most_common():
            lines.append(f"    {gt:>15} → {pred:<15} : {cnt}")

    # 4. Unique divergences
    lines.append("")
    lines.append("4. FILES WHERE EXTRACTORS DISAGREE")
    lines.append("-" * 60)
    disagree_count = 0
    for r in rows:
        classes = set(r[f"{ext}_class"] for ext in ext_names)
        if len(classes) > 1:
            disagree_count += 1
            if disagree_count <= 30:  # show first 30
                detail = " | ".join(f"{ext}={r[f'{ext}_class']}" for ext in ext_names)
                lines.append(f"  {r['file']}")
                lines.append(f"    GT={r['ground_truth']} | {detail}")
    lines.append(f"\n  Total disagreements: {disagree_count} / {total}")

    # 5. Итоговый рейтинг: качество + скорость
    lines.append("")
    lines.append("5. QUALITY-SPEED RANKING")
    lines.append("-" * 60)
    lines.append(f"  {'Extractor':<18} {'Accuracy':>8} {'AvgTime':>9} {'TotalTime':>10} {'Score':>7}")
    lines.append(f"  {'(quality→speed)':>18} {'(%)':>8} {'(s/file)':>9} {'(s)':>10} {'(q*1/t)':>7}")
    lines.append("")

    rankings = []
    for ext in ext_names:
        ok = sum(1 for r in rows if r[f"{ext}_match"] == "OK")
        acc = ok / total * 100 if total else 0
        avg_t = sum(r[f"{ext}_time"] for r in rows) / total if total else 0
        total_t = sum(r[f"{ext}_time"] for r in rows)
        # Score = accuracy * (1 / avg_time) — выше = лучше качество за меньшее время
        score = acc / avg_t if avg_t > 0 else 0
        rankings.append((ext, acc, avg_t, total_t, score))

    # Сортировка: сначала по accuracy DESC, потом по avg_time ASC
    rankings.sort(key=lambda x: (-x[1], x[2]))
    for rank, (ext, acc, avg_t, total_t, score) in enumerate(rankings, 1):
        marker = " ★" if rank == 1 else ""
        lines.append(f"  {rank}. {ext:<16} {acc:>7.1f}% {avg_t:>8.3f}s {total_t:>9.1f}s {score:>7.1f}{marker}")

    lines.append("")
    best = rankings[0]
    lines.append(f"  BEST QUALITY:  {best[0]} ({best[1]:.1f}%)")
    # Fastest among top accuracy (within 1% of best)
    top_acc = best[1]
    fast_among_top = [r for r in rankings if r[1] >= top_acc - 1.0]
    fast_among_top.sort(key=lambda x: x[2])
    lines.append(f"  BEST SPEED (top quality group): {fast_among_top[0][0]} ({fast_among_top[0][2]:.3f}s/file)")
    # Best score (balance)
    by_score = sorted(rankings, key=lambda x: -x[4])
    lines.append(f"  BEST BALANCE (quality/speed):   {by_score[0][0]} (score={by_score[0][4]:.1f})")

    return lines


if __name__ == "__main__":
    run_benchmark()
