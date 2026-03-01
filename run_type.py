from __future__ import annotations
import time
from pathlib import Path
from typing import Optional, Tuple, Iterable, List
import glob
import shutil

from config import (
    ROOTS_GLOB, LOG_TO_CONSOLE, NAME_CONFLICT_POLICY,
    LABEL_IMG_FILE, LABEL_NOMASK, bucket_name, IMAGE_EXTS, SPEED_BATCH, SPEED_LOG
)
from scanner import iter_root_dirs
from mover import safe_move


def short_ts() -> str:
    import time
    return time.strftime("%d.%m %H:%M:%S")
### ======= Тайм ====== №№№
def format_eta(seconds: float) -> str:
    s = int(max(0, seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:   return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

class SpeedTracker:
    def __init__(self, total:int|None, batch_size:int):
        self.total = total
        self.batch_size = batch_size
        self.overall_start = time.perf_counter()
        self.batch_start = self.overall_start
        self.done = 0

    def tick_and_maybe_log(self, log_fn, where:str=""):
        self.done += 1
        if self.done % self.batch_size != 0:
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
            eta = f" | ETA {format_eta(eta_s)}"
        log_fn(
            f"{short_ts()} {where} {self.done}/{self.total or '?'} | "
            f"last {self.batch_size}: {batch_dt:.2f}s ⇒ {batch_speed:.2f} file/s | "
            f"overall: {overall_speed:.2f} file/s{eta}"
        )

        self.batch_start = now
###########################


# ---------- ЛОГ ----------
def log(msg: str) -> None:
    if LOG_TO_CONSOLE:
        print(msg)

# ---------- ДЕТЕКТ ПО СИГНАТУРАМ ----------
def sniff_type(fp: Path) -> Optional[Tuple[str, str]]:
    """
    Возвращает ('image', 'jpg'|'png'|...|'heic') или ('pdf','pdf'), иначе None.
    """
    try:
        with fp.open("rb") as f:
            head = f.read(4096)
    except Exception:
        return None

    if not head:
        return None

    # PDF: %PDF-
    if head.startswith(b"%PDF-"):
        return ("pdf", "pdf")

    # JPEG: FF D8 FF
    if head[:3] == b"\xFF\xD8\xFF":
        return ("image", "jpg")

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ("image", "png")

    # GIF: GIF87a / GIF89a
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return ("image", "gif")

    # TIFF: II*\x00 или MM\x00*
    if head.startswith(b"II*\x00") or head.startswith(b"MM\x00*"):
        return ("image", "tiff")

    # BMP: 'BM'
    if head.startswith(b"BM"):
        return ("image", "bmp")

    # WEBP: 'RIFF'....'WEBP'
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ("image", "webp")

    # HEIC/HEIF/AVIF (простая эвристика по 'ftyp' боксам)
    # Ищем 'ftyp' и brand с 'heic'/'heif'/'heix'/'hevc'/'avif'
    if b"ftyp" in head[:64]:
        idx = head.find(b"ftyp")
        brand = head[idx+4:idx+8] if idx != -1 else b""
        if brand in (b"heic", b"heix", b"hevc", b"heif", b"mif1", b"msf1", b"avif", b"avis"):
            # В вашем списке целевых форматов только heic из «современных»
            return ("image", "heic")

    return None

# ---------- ИМЕНА ПАПОК ----------
def img_dir(root: Path) -> Path:
    p = root / bucket_name(root, LABEL_IMG_FILE)
    p.mkdir(parents=True, exist_ok=True)
    return p

def nomask_dir(root: Path) -> Path:
    p = root / bucket_name(root, LABEL_NOMASK)
    p.mkdir(parents=True, exist_ok=True)
    return p

# ---------- УНИКАЛЬНОЕ ИМЯ ----------
def unique_path(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem, suf = dst.stem, dst.suffix
    i = 1
    while True:
        cand = dst.with_name(f"{stem}_{i}{suf}")
        if not cand.exists():
            return cand
        i += 1

# ---------- ДОБАВИТЬ РАСШИРЕНИЕ (БЕЗ ПЕРЕЗАПИСИ) ----------
def add_ext_unique(fp: Path, new_ext: str) -> Path:
    """
    Добавляет расширение .new_ext к файлу fp в той же папке.
    Возвращает итоговый путь.
    """
    new_name = fp.name + ("" if new_ext.startswith(".") else ".") + new_ext
    dst = fp.with_name(new_name)
    if dst.exists():
        dst = unique_path(dst)
    fp.rename(dst)
    return dst

# ---------- ОСНОВНАЯ ЛОГИКА ДЛЯ ОДНОГО ФАЙЛА ----------
def process_file(root: Path, fp: Path) -> Tuple[str, Path]:
    """
    Возвращает (label, final_path):
      - 'img'      -> добавлено расширение и перемещено в IMG_FILE
      - 'pdf'      -> добавлено расширение .pdf (оставлен в исходной папке)
      - 'nomask'   -> перемещено в NOMASK
      - 'skip'     -> пропуск (уже имеет норм. расширение или неподходящее)
    """
    try:
        if not fp.is_file():
            return ("skip", fp)

        # Пропускаем наши бренд-папки
        branded = {
            bucket_name(root, LABEL_IMG_FILE),
            bucket_name(root, LABEL_NOMASK),
        }
        if any((root / bname) in fp.parents for bname in branded):
            return ("skip", fp)

        # Если расширение уже есть и оно из допустимых (pdf или целевые картинки) — пропуск
        suf = fp.suffix.lower().lstrip(".")
        if suf in ({"pdf"} | {e.lower() for e in IMAGE_EXTS}):
            return ("skip", fp)

        # Определяем тип
        kind = sniff_type(fp)
        if kind is None:
            # Не распознали — в NOMASK
            dst_dir = nomask_dir(root)
            dst, _ = safe_move(fp, dst_dir)
            return ("nomask", dst)

        typ, ext = kind

        if typ == "image":
            # добавляем расширение и переносим в IMG_FILE
            fp_fixed = add_ext_unique(fp, ext)
            dst_dir = img_dir(root)
            dst, _ = safe_move(fp_fixed, dst_dir)
            return ("img", dst)

        if typ == "pdf":
            # добавляем .pdf, не переносим (пусть run_pdfs потом разложит)
            fp_fixed = add_ext_unique(fp, "pdf")
            return ("pdf", fp_fixed)

        # На всякий случай
        dst_dir = nomask_dir(root)
        dst, _ = safe_move(fp, dst_dir)
        return ("nomask", dst)

    except Exception as e:
        log(f"[ERROR] {fp}: {e}")
        return ("skip", fp)

# ---------- ПРОХОД ПО КОРНЮ ----------
def process_root(root: Path) -> Tuple[int,int,int,int]:
    moved_img = fixed_pdf = moved_nomask = skipped = 0
    log(f"[Root] {root}")

    files = [p for p in root.rglob("*") if p.is_file()]
    st = SpeedTracker(total=len(files), batch_size=SPEED_BATCH)

    for fp in (p for p in root.rglob("*") if p.is_file()):
        label, _dst = process_file(root, fp)
        if label == "img":
            moved_img += 1
        elif label == "pdf":
            fixed_pdf += 1
        elif label == "nomask":
            moved_nomask += 1
        else:
            skipped += 1

        if SPEED_LOG:
            st.tick_and_maybe_log(log, where=f"[{root.name} TYPEFIX]")

    log(f"[Summary typefix] {root}  img={moved_img} pdf_fixed={fixed_pdf} nomask={moved_nomask} skip={skipped}")
    return moved_img, fixed_pdf, moved_nomask, skipped

# ---------- MAIN ----------
def main() -> Tuple[int,int,int,int]:
    total = [0,0,0,0]
    log(f"[Start TYPEFIX] roots: {ROOTS_GLOB}")
    for root in iter_root_dirs(ROOTS_GLOB):
        res = process_root(root)
        total = [a+b for a,b in zip(total, res)]
    log(f"[Total TYPEFIX] img={total[0]} pdf_fixed={total[1]} nomask={total[2]} skip={total[3]}")
    return tuple(total)  # type: ignore[return-value]

if __name__ == "__main__":
    main()
