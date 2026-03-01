from pathlib import Path
from typing import Tuple
import time
from config import (
    ROOTS_GLOB, LABEL_IMG_FILE, bucket_name, IMAGE_EXTS,
    NAME_CONFLICT_POLICY, LOG_TO_CONSOLE, SPEED_BATCH, SPEED_LOG, SPEED_ONLY
)
from scanner import iter_root_dirs, iter_image_files_in_root
from mover import safe_move


def short_ts() -> str:
    import time
    return time.strftime("%d.%m %H:%M:%S")

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

def log(msg: str) -> None:
    if LOG_TO_CONSOLE:
        print(msg)

def process_root(root: Path) -> Tuple[int, int]:
    moved = renamed = 0
    dest_dir = root / bucket_name(root, LABEL_IMG_FILE)
    dest_dir.mkdir(parents=True, exist_ok=True)
    exclude_names = {dest_dir.name}

    # заранее считаем список, чтобы знать total
    files = list(iter_image_files_in_root(root, IMAGE_EXTS, exclude_names))
    st = SpeedTracker(total=len(files), batch_size=SPEED_BATCH)

    for src in files:
        try:
            if dest_dir in src.parents:
                continue
            dst, was_renamed = safe_move(src, dest_dir, policy=NAME_CONFLICT_POLICY)
            moved += 1
            renamed += int(was_renamed)
        except Exception:
            if not SPEED_ONLY:
                log(f"[ERROR] {src}")

        if SPEED_LOG:
            st.tick_and_maybe_log(log, where=f"[{root.name} IMG]")

    log(f"[Done] {root}  moved={moved}, renamed={renamed}")
    return moved, renamed

def main() -> Tuple[int, int]:
    total_moved = 0
    total_renamed = 0

    log(f"[Start] scan roots: {ROOTS_GLOB}")
    for root in iter_root_dirs(ROOTS_GLOB):
        log(f"[Root ] {root}")
        m, r = process_root(root)
        total_moved += m
        total_renamed += r

    log(f"[Total] moved={total_moved}, renamed={total_renamed}")
    return total_moved, total_renamed

if __name__ == "__main__":
    main()
