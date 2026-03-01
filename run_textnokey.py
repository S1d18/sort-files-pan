# run_textnokey.py — OCR-переклассификация файлов из text_pdf(nokey)
from __future__ import annotations

import datetime
import os
import time
from pathlib import Path
from typing import Tuple
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

from config import (
    ROOTS_GLOB, LOG_TO_CONSOLE, NAME_CONFLICT_POLICY,
    LABEL_BILL_PDF, LABEL_TEXT_NOKEY,
    bucket_name, wordList, VALID_YEAR_RANGE,
    SPEED_BATCH, SPEED_LOG, SPEED_ONLY,
    PDF_WORKERS, OCR_DPI, OCR_MAX_PAGES, OCR_LANG,
)
from scanner import iter_root_dirs
from text_rules import (
    prepare_needles, contains_any_prepared,
    extract_years, pick_year_for_folder,
)

import re

WORDS = prepare_needles(wordList)
MAX_WIN_WORKERS = 61

_TLD_RE = re.compile(r'@[a-zA-Z0-9\.-]+\.(\w+)', re.IGNORECASE)


def _extract_tld_from_filename(name: str) -> str | None:
    m = _TLD_RE.search(name)
    return m.group(1).lower() if m else None


def _ts() -> str:
    return time.strftime("%d.%m %H:%M:%S")


def log(msg: str) -> None:
    if LOG_TO_CONSOLE:
        print(msg)


def _fmt_eta(seconds: float) -> str:
    s = int(max(0, seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class SpeedTracker:
    def __init__(self, total: int | None, batch_size: int):
        self.total = total
        self.batch_size = batch_size
        self.overall_start = time.perf_counter()
        self.batch_start = self.overall_start
        self.done = 0

    def tick_and_maybe_log(self, where: str = ""):
        self.done += 1
        if not SPEED_LOG or self.done % self.batch_size != 0:
            return
        now = time.perf_counter()
        batch_dt = now - self.batch_start
        overall_dt = now - self.overall_start
        batch_speed = self.batch_size / batch_dt if batch_dt > 0 else float("inf")
        overall_speed = self.done / overall_dt if overall_dt > 0 else float("inf")
        eta = ""
        if self.total:
            left = max(0, self.total - self.done)
            eta_s = left / overall_speed if overall_speed > 0 else 0
            eta = f" | ETA {_fmt_eta(eta_s)}"
        log(
            f"{_ts()} {where} {self.done}/{self.total or '?'} | "
            f"last {self.batch_size}: {batch_dt:.2f}s => {batch_speed:.2f} file/s | "
            f"overall: {overall_speed:.2f} file/s{eta}"
        )
        self.batch_start = now


def _bucket(root: Path, label: str) -> Path:
    p = root / bucket_name(root, label)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ocr_pdf(pdf_path: Path) -> str:
    """Рендер страниц PDF в изображения и OCR через pytesseract."""
    import fitz
    import pytesseract
    from PIL import Image
    import io

    texts: list[str] = []
    doc = fitz.open(str(pdf_path))
    try:
        n_pages = min(len(doc), OCR_MAX_PAGES)
        for i in range(n_pages):
            page = doc[i]
            mat = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(
                img, lang=OCR_LANG,
                config="--psm 3 --oem 3",
            )
            if text:
                texts.append(text)
    finally:
        doc.close()

    return "\n".join(texts)


def classify_one(args: tuple[str, str]) -> tuple[str, str]:
    root_str, pdf_str = args
    root = Path(root_str)
    pdf_path = Path(pdf_str)

    from mover import safe_move

    try:
        text = _ocr_pdf(pdf_path)
    except Exception:
        return ("stayed", str(pdf_path))

    t_strip = text.strip()
    if not t_strip:
        return ("stayed", str(pdf_path))

    if contains_any_prepared(t_strip, WORDS):
        years = extract_years(t_strip, VALID_YEAR_RANGE)
        year = pick_year_for_folder(years)

        base = _bucket(root, LABEL_BILL_PDF) / "OCR"
        base.mkdir(parents=True, exist_ok=True)
        this_year = datetime.datetime.now().year
        if year in {this_year - 1, this_year, this_year + 1}:
            base = base / str(year)
            base.mkdir(parents=True, exist_ok=True)

        tld = _extract_tld_from_filename(pdf_path.name)
        target = base / tld if tld else base
        target.mkdir(parents=True, exist_ok=True)

        dst, _ = safe_move(pdf_path, target, policy=NAME_CONFLICT_POLICY)
        return ("bill", str(dst))

    return ("stayed", str(pdf_path))


def _safe_classify(args: tuple[str, str]) -> tuple[str, str]:
    try:
        return classify_one(args)
    except Exception as e:
        return ("stayed", f"{e!s}")


def process_root(root: Path) -> Tuple[int, int]:
    nokey_dir = root / bucket_name(root, LABEL_TEXT_NOKEY)
    if not nokey_dir.is_dir():
        return (0, 0)

    files = [p for p in nokey_dir.rglob("*.pdf") if p.is_file()]
    total = len(files)
    if total == 0:
        return (0, 0)

    log(f"{_ts()} [{root.name} OCR] {total} PDFs in text_nokey")

    st = SpeedTracker(total=total, batch_size=SPEED_BATCH)
    stats = Counter()

    if PDF_WORKERS and PDF_WORKERS > 0:
        workers = int(PDF_WORKERS)
    else:
        cpu = os.cpu_count() or 1
        workers = max(1, cpu - 1)

    if os.name == "nt" and workers > MAX_WIN_WORKERS:
        workers = MAX_WIN_WORKERS
    workers = max(1, workers)

    args_list = [(str(root), str(p)) for p in files]

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_safe_classify, a) for a in args_list]
        for fut in as_completed(futures):
            try:
                label, payload = fut.result()
            except BaseException as e:
                stats["stayed"] += 1
                if not SPEED_ONLY:
                    log(f"{_ts()} [OCR ERR] {type(e).__name__}: {e!s}")
            else:
                stats[label] += 1
            st.tick_and_maybe_log(where=f"[{root.name} OCR]")

    return (stats["bill"], stats["stayed"])


def run() -> Tuple[int, int]:
    bill_total = 0
    stayed_total = 0
    log(f"[Start OCR textnokey] roots: {ROOTS_GLOB}")
    for root in iter_root_dirs(ROOTS_GLOB):
        bill, stayed = process_root(root)
        bill_total += bill
        stayed_total += stayed
        if not SPEED_ONLY:
            log(f"[OCR {root.name}] reclassified={bill} stayed={stayed}")

    log(f"[OCR Total] reclassified={bill_total} stayed={stayed_total}")
    return (bill_total, stayed_total)


if __name__ == "__main__":
    run()
