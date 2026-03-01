# benchmark_compare.py — сравнение классификации bas vs python
# Создаёт CSV: filename, bas_category, python_category
import os
import csv
from pathlib import Path
from collections import defaultdict

BAS_ROOT = r"M:\bas_Files289"
PY_ROOT = r"M:\python_Files289"
OUT_CSV = r"M:\compare_289.csv"


def scan_tree(root: str) -> dict[str, str]:
    """filename -> category (subfolder name relative to root)"""
    result = {}
    root_p = Path(root)
    for dirpath, _, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root_p)
        cat = str(rel) if str(rel) != "." else "(root)"
        for f in filenames:
            result[f] = cat
    return result


def main():
    print(f"Scanning {BAS_ROOT} ...")
    bas = scan_tree(BAS_ROOT)
    print(f"  {len(bas)} files")

    print(f"Scanning {PY_ROOT} ...")
    py = scan_tree(PY_ROOT)
    print(f"  {len(py)} files")

    all_files = sorted(set(bas) | set(py))
    print(f"Total unique filenames: {len(all_files)}")

    match = 0
    diff = 0

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["filename", "bas_category", "python_category", "match"])
        for name in all_files:
            b = bas.get(name, "(missing)")
            p = py.get(name, "(missing)")
            is_match = b == p
            if is_match:
                match += 1
            else:
                diff += 1
            w.writerow([name, b, p, "YES" if is_match else "NO"])

    print(f"\nResults: {match} match, {diff} differ")
    print(f"CSV saved: {OUT_CSV}")

    # Сводка различий по категориям
    diffs = defaultdict(int)
    for name in all_files:
        b = bas.get(name, "(missing)")
        p = py.get(name, "(missing)")
        if b != p:
            diffs[(b, p)] += 1

    if diffs:
        print("\nDifferences summary (bas -> python : count):")
        for (b, p), cnt in sorted(diffs.items(), key=lambda x: -x[1]):
            print(f"  {b}  ->  {p}  : {cnt}")


if __name__ == "__main__":
    main()
