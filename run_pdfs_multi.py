# run_pdfs_multi.py
from __future__ import annotations

import datetime
import os
import re
import time
from pathlib import Path
from typing import Tuple
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

from config import (
    ROOTS_GLOB, LOG_TO_CONSOLE, NAME_CONFLICT_POLICY,
    LABEL_FILEPDF_ERR, LABEL_BLOCKPDF, LABEL_IMG_PDF,
    LABEL_BILL_PDF, LABEL_BILL_MUSOR, LABEL_TEXT_NOKEY,
    bucket_name, wordList, wordListMusor, VALID_YEAR_RANGE,
    SPEED_BATCH, SPEED_LOG, SPEED_ONLY, PDF_WORKERS
)
from scanner import iter_root_dirs, iter_pdf_files_in_root

# --- Текстовые правила ---
from text_rules import (
    prepare_needles, contains_any_prepared,
    extract_years, pick_year_for_folder
)

import warnings
try:
    from PyPDF2.errors import PdfReadWarning
except Exception:
    class PdfReadWarning(Warning): ...
warnings.simplefilter("ignore", PdfReadWarning)

WORDS = prepare_needles(wordList)
WORDS_MUSOR = prepare_needles(wordListMusor)
MAX_WIN_WORKERS = 61  # лимит ProcessPoolExecutor на Windows

LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
DIGIT_RE  = re.compile(r"\d")

def _has_letter_and_digit(t: str) -> bool:
    return bool(LETTER_RE.search(t)) and bool(DIGIT_RE.search(t))

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
            f"last {self.batch_size}: {batch_dt:.2f}s ⇒ {batch_speed:.2f} file/s | "
            f"overall: {overall_speed:.2f} file/s{eta}"
        )
        self.batch_start = now

_TLD_RE = re.compile(r'@[a-zA-Z0-9\.-]+\.(\w+)', re.IGNORECASE)
def _extract_tld_from_filename(name: str) -> str | None:
    m = _TLD_RE.search(name)
    return m.group(1).lower() if m else None

def _bucket(root: Path, label: str) -> Path:
    p = root / bucket_name(root, label)
    p.mkdir(parents=True, exist_ok=True)
    return p

def classify_one(args: tuple[str, str]) -> tuple[str, str]:
    root_str, pdf_str = args
    root = Path(root_str)
    pdf_path = Path(pdf_str)

    from pdf_text import extract_pdf_text, PDFOpenError, PDFBlockedError
    from mover import safe_move

    try:
        text = extract_pdf_text(pdf_path)
    except PDFBlockedError:
        target = _bucket(root, LABEL_BLOCKPDF)
        dst, _ = safe_move(pdf_path, target, policy=NAME_CONFLICT_POLICY)
        return ("blocked", str(dst))
    except Exception:
        target = _bucket(root, LABEL_FILEPDF_ERR)
        dst, _ = safe_move(pdf_path, target, policy=NAME_CONFLICT_POLICY)
        return ("error", str(dst))

    t_strip = (text or "").strip()

    if not t_strip or not _has_letter_and_digit(t_strip):
        target = _bucket(root, LABEL_IMG_PDF)
        dst, _ = safe_move(pdf_path, target, policy=NAME_CONFLICT_POLICY)
        return ("image_pdf", str(dst))

    if contains_any_prepared(t_strip, WORDS_MUSOR):
        target = _bucket(root, LABEL_BILL_MUSOR)
        dst, _ = safe_move(pdf_path, target, policy=NAME_CONFLICT_POLICY)
        return ("bill_musor", str(dst))

    if contains_any_prepared(t_strip, WORDS):
        years = extract_years(t_strip, VALID_YEAR_RANGE)
        year = pick_year_for_folder(years)

        base = _bucket(root, LABEL_BILL_PDF)
        this_year = datetime.datetime.now().year
        if year in {this_year - 1, this_year, this_year + 1}:
            base = base / str(year)
            base.mkdir(parents=True, exist_ok=True)

        tld = _extract_tld_from_filename(pdf_path.name)
        target = base / tld if tld else base
        target.mkdir(parents=True, exist_ok=True)

        dst, _ = safe_move(pdf_path, target, policy=NAME_CONFLICT_POLICY)
        return ("bill", str(dst))

    target = _bucket(root, LABEL_TEXT_NOKEY)
    dst, _ = safe_move(pdf_path, target, policy=NAME_CONFLICT_POLICY)
    return ("text_nokey", str(dst))

def _safe_classify(args: tuple[str, str]) -> tuple[str, str]:
    try:
        return classify_one(args)
    except Exception as e:
        return ("error", f"{e!s}")

def process_root(root: Path) -> Tuple[int, int, int, int, int, int]:
    exclude_names = {
        bucket_name(root, LABEL_FILEPDF_ERR),
        bucket_name(root, LABEL_BLOCKPDF),
        bucket_name(root, LABEL_IMG_PDF),
        bucket_name(root, LABEL_BILL_PDF),
        bucket_name(root, LABEL_BILL_MUSOR),
        bucket_name(root, LABEL_TEXT_NOKEY),
    }

    files = list(iter_pdf_files_in_root(root, exclude_names))
    total = len(files)
    if total == 0:
        return (0, 0, 0, 0, 0, 0)

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

    # submit + as_completed — устойчиво к «внезапной» ошибке в воркере
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_safe_classify, a) for a in args_list]
        for fut in as_completed(futures):
            try:
                label, payload = fut.result()
            except BaseException as e:
                stats["error"] += 1
                if not SPEED_ONLY:
                    log(f"{_ts()} [PDF ERR] {type(e).__name__}: {e!s}")
            else:
                if label == "error":
                    stats["error"] += 1
                    if not SPEED_ONLY and isinstance(payload, str) and payload:
                        log(f"{_ts()} [PDF ERR] {payload}")
                else:
                    stats[label] += 1
            st.tick_and_maybe_log(where=f"[{root.name} PDF]")

    return (
        stats["error"],
        stats["blocked"],
        stats["image_pdf"],
        stats["bill_musor"],
        stats["bill"],
        stats["text_nokey"],
    )

def run() -> Tuple[int, int, int, int, int, int]:
    total = [0, 0, 0, 0, 0, 0]
    log(f"[Start PDF] roots: {ROOTS_GLOB}")
    for root in iter_root_dirs(ROOTS_GLOB):
        log(f"[Root] {root}")
        res = process_root(root)
        total = [a + b for a, b in zip(total, res)]
        if not SPEED_ONLY:
            log(
                f"[Summary root] err={res[0]} blocked={res[1]} img={res[2]} "
                f"musor={res[3]} bill={res[4]} nokey={res[5]}"
            )

    log(
        f"[Total] err={total[0]} blocked={total[1]} img={total[2]} "
        f"musor={total[3]} bill={total[4]} nokey={total[5]}"
    )
    return tuple(total)  # type: ignore[return-value]

if __name__ == "__main__":
    run()
