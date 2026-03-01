# rename_parent_label_suffix_robust_v2.py
from pathlib import Path
import os, sys, time, re
from collections import Counter

TARGETS = {
    "IMG_FILE":        "img_file",
    "IMG_PDF":         "img_pdf",
    "BLOCK_PDF":       "block_pdf",
    "FILEPDF_ERROR":   "file_error",
    "FILE_ERROR":      "file_error",      # <-- добавили это
    "BILL_PDF":        "bill_pdf",
    "BILL_MUSOR_PDF":  "bill_musor_pdf",
    "TEXT_PDF(NOKEY)": "text_pdf(nokey)",
    "NOMASK":          "nomask",
}

PAT = re.compile(r"^(?P<prefix>.+?)\s*\((?P<label>.+?)\)\s*$")

def canon(label: str) -> str:
    s = label.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("-", "_")
    s = s.replace(" (", "(").replace(") ", ")")
    return s.upper()

def safe_rename(src: Path, dst: Path, dry_run: bool, verbose: bool, force: bool) -> bool:
    # если строково имена равны — нечего делать (редкий случай)
    if src.name == dst.name and not force:
        if verbose: print(f"[SKIP=same-name] {src.name}")
        return False

    # Если целевой путь существует:
    if dst.exists():
        try:
            # Это Тот Же каталог (NTFS case-insensitive) -> всё равно делаем «хоп»,
            # чтобы сменить регистр/пробелы/скобки и т.п.
            if os.path.samefile(src, dst):
                if verbose: print(f"[HOP] samefile {src.name} -> {dst.name}")
            else:
                # Реально другой каталог с таким именем — опасно, пропускаем
                if verbose: print(f"[SKIP=conflict] {src.name} -> {dst.name} (other dir exists)")
                return False
        except Exception:
            if verbose: print(f"[SKIP=exists-unknown] {src.name} -> {dst.name}")
            return False

    if dry_run:
        print(f"[DRY] {src.name}  ->  {dst.name}")
        return True

    tmp = src.parent / f"__casefix__{int(time.time()*1000)}__{os.getpid()}__"
    try:
        os.replace(src, tmp)
        os.replace(tmp, dst)
        print(f"[OK ] {src.name}  ->  {dst.name}")
        return True
    except Exception as e:
        # откат
        if tmp.exists() and not src.exists():
            try: os.replace(tmp, src)
            except Exception: pass
        print(f"[ERR] {src} -> {dst}: {e}")
        return False

def run(root: Path, keep_prefix: bool, dry_run: bool, verbose: bool, force: bool):
    total = changed = 0
    seen = Counter()
    unmatched = []

    for p in root.rglob("*"):
        if not p.is_dir():
            continue
        m = PAT.match(p.name)
        if not m:
            continue

        raw_label = m.group("label")
        key = canon(raw_label)
        seen[key] += 1

        target_lower = TARGETS.get(key)
        if not target_lower:
            if len(unmatched) < 20:
                unmatched.append(p.name)
            if verbose:
                print(f"[UNMAPPED] {p.name}  (canon={key})")
            continue

        new_name = f"{m.group('prefix').rstrip()} ({target_lower})" if keep_prefix else target_lower

        if new_name == p.name and not force:
            if verbose:
                print(f"[SKIP=already] {p.name}")
            continue

        total += 1
        dst = p.parent / new_name
        if safe_rename(p, dst, dry_run, verbose, force):
            changed += 1

    print(f"\nИтог по {root}: найдено={total}, переименовано={changed}, dry_run={dry_run}, keep_prefix={keep_prefix}, force={force}")
    print("\nСтатистика меток (после нормализации):")
    for k, v in seen.most_common():
        print(f"  {k}: {v}")

    if unmatched:
        print("\nНеизвестные метки (добавь ключ в TARGETS, ключ = canon() в ВЕРХНЕМ регистре):")
        for name in unmatched:
            print(" ", name)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python rename_parent_label_suffix_robust_v2.py <ROOT> [--apply] [--just-label] [--verbose] [--force]")
        sys.exit(1)

    root = Path(sys.argv[1]).resolve()
    dry_run = "--apply" not in sys.argv[2:]
    keep_prefix = "--just-label" not in sys.argv[2:]
    verbose = "--verbose" in sys.argv[2:]
    force = "--force" in sys.argv[2:]

    print(f"Старт: root={root}, dry_run={dry_run}, keep_prefix={keep_prefix}, verbose={verbose}, force={force}")
    run(root, keep_prefix=keep_prefix, dry_run=dry_run, verbose=verbose, force=force)
