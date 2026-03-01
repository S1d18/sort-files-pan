# clean_temp.py
# Очистка %LOCALAPPDATA%\Temp (или указанной папки) от файлов/папок старше "вчера 00:00".
# Пример: python clean_temp.py --dry-run   (только покажет, что бы удалил)

from __future__ import annotations
import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

def ts() -> str:
    return time.strftime("%d.%m %H:%M:%S")

def human(n: int) -> str:
    for unit in ("B","KB","MB","GB","TB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} PB"

def start_of_yesterday() -> datetime:
    now = datetime.now()
    today00 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today00 - timedelta(days=1)

def file_age_dt(p: Path) -> datetime:
    # На Windows ctime — creation time, mtime — modification time.
    st = p.stat()
    return datetime.fromtimestamp(max(st.st_mtime, st.st_ctime))

def is_inside(child: Path, parent: Path) -> bool:
    try:
        child_r = child.resolve()
        parent_r = parent.resolve()
        return parent_r in child_r.parents or child_r == parent_r
    except Exception:
        return False

def try_remove_file(p: Path) -> tuple[bool, str]:
    try:
        # Снимаем read-only, если есть
        try:
            os.chmod(p, 0o666)
        except Exception:
            pass
        p.unlink()
        return True, ""
    except PermissionError as e:
        return False, f"PermissionError: {e}"
    except OSError as e:
        return False, f"OSError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def try_remove_dir(p: Path) -> tuple[bool, str]:
    try:
        shutil.rmtree(p, ignore_errors=False)
        return True, ""
    except PermissionError as e:
        return False, f"PermissionError: {e}"
    except OSError as e:
        return False, f"OSError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def enumerate_targets(temp_dir: Path, cutoff: datetime):
    """Даёт элементы на удаление: сначала файлы, затем пустые папки (глубокие сначала)."""
    files = []
    dirs = []
    for root, dirnames, filenames in os.walk(temp_dir):
        root_p = Path(root)
        # Файлы
        for name in filenames:
            p = root_p / name
            try:
                age = file_age_dt(p)
            except Exception:
                continue
            if age < cutoff:
                files.append(p)
        # Папки — добавим после обхода (сортировкой по глубине)
        for name in dirnames:
            dirs.append(root_p / name)

    # Сортируем папки по убыванию глубины, чтобы удалять «внутри → наружу»
    dirs.sort(key=lambda d: len(d.parts), reverse=True)
    return files, dirs

def main():
    parser = argparse.ArgumentParser(
        description="Очистка Temp от файлов/папок старше 'вчера 00:00'."
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Путь к Temp. По умолчанию: %LOCALAPPDATA%\\Temp",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, что будет удалено (без удаления).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Подробный вывод (каждый удалённый/пропущенный элемент).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Вместо 'вчера 00:00' — удалить старше N дней от текущего момента.",
    )
    args = parser.parse_args()

    # Определяем Temp
    if args.path:
        temp_dir = Path(args.path)
    else:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            print("Не найден %LOCALAPPDATA%. Укажите --path.", file=sys.stderr)
            sys.exit(2)
        temp_dir = Path(local) / "Temp"

    if not temp_dir.exists() or not temp_dir.is_dir():
        print(f"Папка не найдена: {temp_dir}", file=sys.stderr)
        sys.exit(2)

    # Защита от случайного удаления «не того»: убеждаемся, что путь похож на Temp
    if "temp" not in temp_dir.name.lower():
        print(f"Страховка: путь не похож на Temp: {temp_dir}", file=sys.stderr)
        sys.exit(2)

    # Дата отсечения
    if args.days is not None and args.days > 0:
        cutoff = datetime.now() - timedelta(days=args.days)
    else:
        cutoff = start_of_yesterday()

    print(f"{ts()} [START] Temp: {temp_dir}")
    print(f"{ts()} [CUT  ] Удаляем всё старше: {cutoff.strftime('%d.%m.%Y %H:%M:%S')}")
    if args.dry_run:
        print(f"{ts()} [MODE ] DRY-RUN (без удаления)")

    files, dirs = enumerate_targets(temp_dir, cutoff)

    total_files = len(files)
    total_dirs = len(dirs)

    deleted_files = 0
    deleted_dirs = 0
    failed = 0
    bytes_planned = 0
    bytes_deleted = 0

    # Суммируем размер заранее по файлам
    for f in files:
        try:
            bytes_planned += f.stat().st_size
        except Exception:
            pass

    # Удаляем файлы
    for f in files:
        if args.dry_run:
            if args.verbose:
                print(f"[FILE] {f}")
            continue
        ok, err = try_remove_file(f)
        if ok:
            deleted_files += 1
            try:
                bytes_deleted += 0  # размер уже посчитан заранее
            except Exception:
                pass
            if args.verbose:
                print(f"[DEL ] {f}")
        else:
            failed += 1
            if args.verbose:
                print(f"[FAIL] {f} — {err}")

    # Удаляем папки (попытаемся только те, что стали пустыми/старыми)
    for d in dirs:
        # Если папка сама моложе cutoff — пропустим.
        try:
            if file_age_dt(d) >= cutoff:
                continue
        except Exception:
            pass
        if args.dry_run:
            if args.verbose:
                print(f"[DIR ] {d}")
            continue
        # Если не пуста, rmtree всё равно удалит содержимое. Это нормально,
        # потому что внутри уже старые элементы; новые мы не трогали (фильтровались выше).
        ok, err = try_remove_dir(d)
        if ok:
            deleted_dirs += 1
            if args.verbose:
                print(f"[RMD ] {d}")
        else:
            # Часто бывает занята — пропустим
            if args.verbose:
                print(f"[FAIL] {d} — {err}")

    print(f"{ts()} [DONE ] Files: {deleted_files}/{total_files}, Dirs: {deleted_dirs}/{total_dirs}")
    if bytes_planned:
        print(f"{ts()} [SIZE ] Освобождено потенциально: ≈{human(bytes_planned)} (оценка по файлам)")
    if failed:
        print(f"{ts()} [NOTE ] Не удалось удалить: {failed} объектов (обычно заняты процессами)")

if __name__ == "__main__":
    main()
