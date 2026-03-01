# main.py
from __future__ import annotations
import argparse
import time
import config as cfg


def _fmt_dt(sec: float) -> str:
    s = int(sec)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _run_step(title: str, func):
    print(f"\n=== [{title}] START ===")
    t0 = time.perf_counter()
    try:
        res = func()
    except KeyboardInterrupt:
        print(f"[{title}] Interrupted by user.")
        raise
    except Exception as e:
        print(f"[{title}] ERROR: {e}")
        raise
    dt = time.perf_counter() - t0
    print(f"=== [{title}] DONE in {_fmt_dt(dt)} ===")
    if res is not None:
        print(f"[{title}] result: {res}")
    return res, dt


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Launcher: run_type -> run_images -> run_pdfs -> run_textnokey (OCR)"
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--only", choices=["type", "images", "pdfs", "ocr"],
                   help="Запустить только один шаг.")
    p.add_argument("--skip-type", action="store_true", help="Пропустить run_type")
    p.add_argument("--skip-images", action="store_true", help="Пропустить run_images")
    p.add_argument("--skip-pdfs", action="store_true", help="Пропустить run_pdfs (multi)")
    p.add_argument("--skip-ocr", action="store_true", help="Пропустить OCR textnokey")
    p.add_argument("--quiet", action="store_true", help="Меньше логов")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # применяем тихий режим к конфигу
    if args.quiet:
        cfg.LOG_TO_CONSOLE = False
        cfg.SPEED_LOG = False

    # Импортируем раннеры ТОЛЬКО здесь (важно для Windows spawn)
    import run_type, run_images, run_pdfs_multi, run_textnokey

    # Проталкиваем флаги тишины в раннеры
    run_type.LOG_TO_CONSOLE = cfg.LOG_TO_CONSOLE
    run_images.LOG_TO_CONSOLE = cfg.LOG_TO_CONSOLE
    run_pdfs_multi.LOG_TO_CONSOLE = cfg.LOG_TO_CONSOLE
    run_textnokey.LOG_TO_CONSOLE = cfg.LOG_TO_CONSOLE
    run_type.SPEED_LOG = cfg.SPEED_LOG
    run_images.SPEED_LOG = cfg.SPEED_LOG
    run_pdfs_multi.SPEED_LOG = cfg.SPEED_LOG
    run_textnokey.SPEED_LOG = cfg.SPEED_LOG

    total_time = 0.0
    results = {}

    if args.only == "type" or (not args.only and not args.skip_type):
        res, dt = _run_step("TYPEFIX", run_type.main)
        results["typefix"] = res
        total_time += dt

    if args.only == "images" or (not args.only and not args.skip_images):
        res, dt = _run_step("IMAGES", run_images.main)
        results["images"] = res
        total_time += dt

    if args.only == "pdfs" or (not args.only and not args.skip_pdfs):
        res, dt = _run_step("PDFS", run_pdfs_multi.run)
        results["pdfs"] = res
        total_time += dt

    if args.only == "ocr" or (not args.only and not args.skip_ocr):
        res, dt = _run_step("OCR", run_textnokey.run)
        results["ocr"] = res
        total_time += dt

    print(f"\n[ALL DONE] in {_fmt_dt(total_time)}")
    return results


if __name__ == "__main__":
    main()
