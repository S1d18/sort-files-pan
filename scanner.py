from pathlib import Path
import glob
from typing import Iterator, Set

def iter_root_dirs(roots_glob: str) -> Iterator[Path]:
    for p in glob.glob(roots_glob):
        pp = Path(p)
        if pp.exists() and pp.is_dir():
            yield pp

def iter_image_files_in_root(root: Path, exts: Set[str], exclude_dirnames: Set[str]) -> Iterator[Path]:
    lowered_exts = {e.lower().lstrip(".") for e in exts}
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            for entry in cur.iterdir():
                if entry.is_dir():
                    if entry.is_symlink():
                        continue
                    if entry.name in exclude_dirnames:
                        continue
                    stack.append(entry)
                    continue
                if entry.is_file():
                    ext = entry.suffix.lower().lstrip(".")
                    if ext in lowered_exts:
                        yield entry
        except PermissionError:
            continue

def iter_pdf_files_in_root(root: Path, exclude_dirnames: Set[str]) -> Iterator[Path]:
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            for entry in cur.iterdir():
                if entry.is_dir():
                    if entry.is_symlink():
                        continue  # избегаем циклов/сетевые странности
                    if entry.name in exclude_dirnames:
                        continue
                    stack.append(entry)
                    continue
                if entry.is_file() and entry.suffix.lower() == ".pdf":
                    yield entry
        except PermissionError:
            continue