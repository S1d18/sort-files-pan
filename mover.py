from pathlib import Path
import shutil
import hashlib
from typing import Literal, Tuple

Policy = Literal["increment", "hash", "overwrite"]

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _hash_file(fp: Path, algo="sha1", chunk=1024 * 1024) -> str:
    h = hashlib.new(algo)
    with fp.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def _unique_path_increment(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem, suffix = dst.stem, dst.suffix
    i = 1
    while True:
        candidate = dst.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1

def _unique_path_hash(dst: Path, src_hash: str) -> Path:
    if not dst.exists():
        return dst
    stem, suffix = dst.stem, dst.suffix
    short = src_hash[:8]
    candidate = dst.with_name(f"{stem}_{short}{suffix}")
    # если и такое уже есть — уйдём на increment
    if candidate.exists():
        return _unique_path_increment(dst)
    return candidate

def safe_move(src: Path, dest_dir: Path, policy: Policy = "increment") -> Tuple[Path, bool]:
    """
    Перемещает src в dest_dir, возвращает (итоговый_путь, was_renamed)
    """
    _ensure_dir(dest_dir)
    dst = dest_dir / src.name
    was_renamed = False

    if dst.exists():
        if policy == "overwrite":
            pass  # просто перезапишем
        elif policy == "increment":
            dst = _unique_path_increment(dst)
            was_renamed = True
        elif policy == "hash":
            file_hash = _hash_file(src)
            new_dst = _unique_path_hash(dst, file_hash)
            was_renamed = (new_dst.name != src.name)
            dst = new_dst
        else:
            # на всякий случай
            dst = _unique_path_increment(dst)
            was_renamed = True

    shutil.move(str(src), str(dst))
    return dst, was_renamed