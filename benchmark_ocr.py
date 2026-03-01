"""
Бенчмарк OCR-библиотек на PDF из папки text_pdf(nokey).

Рендерит страницы PDF в изображения через PyMuPDF, прогоняет через
5 OCR-движков и проверяет, находятся ли ключевые слова (wordList/wordListMusor).

Библиотеки:
  1. pytesseract  — Tesseract OCR (CPU)
  2. easyocr      — EasyOCR (GPU/CPU)
  3. rapidocr     — RapidOCR / ONNX (CPU)
  4. doctr        — docTR (GPU/CPU)
  5. paddleocr    — PaddleOCR (CPU/GPU)
"""
from __future__ import annotations

import io
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

# Fix Windows cp1251 + force unbuffered output
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import builtins
_orig_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _orig_print(*args, **kwargs)
builtins.print = print

# ── Конфиг ──
from config import wordList, wordListMusor
from text_rules import prepare_needles, contains_any_prepared

TEST_DIR = Path(r"D:\python\Sort_files_pan\pdf\Files11\Files11 (text_pdf(nokey))")
MAX_PAGES = 3        # OCR только первых N страниц
DPI = 200            # разрешение рендера (баланс скорость/качество)
MAX_FILES = 50       # лимит файлов для бенчмарка (0 = все)

WORDS = prepare_needles(wordList)
WORDS_MUSOR = prepare_needles(wordListMusor)


# ═══════════════════════════════════════════════════════════
#  Рендер PDF → PIL Image
# ═══════════════════════════════════════════════════════════

def pdf_to_images(pdf_path: Path, max_pages: int = MAX_PAGES, dpi: int = DPI) -> list[Image.Image]:
    """Рендерит страницы PDF в PIL Images через PyMuPDF."""
    doc = fitz.open(str(pdf_path))
    images = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
    finally:
        doc.close()
    return images


# ═══════════════════════════════════════════════════════════
#  OCR-экстракторы (ленивая инициализация)
# ═══════════════════════════════════════════════════════════

_engines = {}


def _get_engine(name: str):
    """Ленивая инициализация OCR-движков (чтобы не грузить все сразу)."""
    if name in _engines:
        return _engines[name]

    if name == "pytesseract":
        import pytesseract
        _engines[name] = pytesseract
        return pytesseract

    elif name == "easyocr":
        import easyocr
        reader = easyocr.Reader(
            ["en", "fr"],
            gpu=True,
            verbose=False,
        )
        _engines[name] = reader
        return reader

    elif name == "rapidocr":
        from rapidocr import RapidOCR
        engine = RapidOCR()
        _engines[name] = engine
        return engine

    elif name == "doctr":
        from doctr.models import ocr_predictor
        predictor = ocr_predictor(
            det_arch="db_resnet50",
            reco_arch="crnn_vgg16_bn",
            pretrained=True,
        )
        _engines[name] = predictor
        return predictor

    elif name == "paddleocr":
        import os
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(lang="en")
        _engines[name] = ocr
        return ocr

    raise ValueError(f"Unknown engine: {name}")


def ocr_pytesseract(images: list[Image.Image]) -> str:
    tess = _get_engine("pytesseract")
    parts = []
    for img in images:
        # Мульти-язычный OCR; Tesseract PSM 3 = авто-сегментация
        text = tess.image_to_string(img, lang="eng+fra+deu+rus", config="--psm 3 --oem 3")
        parts.append(text)
    return "\n".join(parts)


def ocr_easyocr(images: list[Image.Image]) -> str:
    import numpy as np
    reader = _get_engine("easyocr")
    parts = []
    for img in images:
        arr = np.array(img)
        results = reader.readtext(arr, detail=0, paragraph=True)
        parts.append("\n".join(results))
    return "\n".join(parts)


def ocr_rapidocr(images: list[Image.Image]) -> str:
    import numpy as np
    engine = _get_engine("rapidocr")
    parts = []
    for img in images:
        arr = np.array(img)
        result = engine(arr)
        if result and result.txts:
            parts.append("\n".join(result.txts))
    return "\n".join(parts)


def ocr_doctr(images: list[Image.Image]) -> str:
    import numpy as np
    predictor = _get_engine("doctr")
    # docTR принимает список numpy-массивов
    arrays = [np.array(img) for img in images]
    result = predictor(arrays)
    parts = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                line_text = " ".join(w.value for w in line.words)
                parts.append(line_text)
    return "\n".join(parts)


def ocr_paddleocr(images: list[Image.Image]) -> str:
    import numpy as np
    ocr = _get_engine("paddleocr")
    parts = []
    for img in images:
        arr = np.array(img)
        result = ocr.predict(arr)
        # PaddleOCR 3.4 predict() returns list of dicts with 'rec_texts'
        if isinstance(result, list):
            for page_res in result:
                if isinstance(page_res, dict):
                    texts = page_res.get("rec_texts", [])
                    parts.extend(texts)
                elif isinstance(page_res, (list, tuple)):
                    # Old API: list of [boxes, (text, conf)]
                    if page_res:
                        for line in page_res:
                            if line and len(line) >= 2:
                                parts.append(str(line[1][0]) if isinstance(line[1], (list, tuple)) else str(line[1]))
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
#  Классификация по OCR-тексту
# ═══════════════════════════════════════════════════════════

def classify_ocr_text(text: str) -> str:
    """Классифицирует текст так же, как run_pdfs_multi."""
    t = (text or "").strip()
    if not t:
        return "no_text"
    if contains_any_prepared(t, WORDS_MUSOR):
        return "bill_musor"
    if contains_any_prepared(t, WORDS):
        return "bill_pdf"
    return "text_nokey"


# ═══════════════════════════════════════════════════════════
#  Главная: бенчмарк
# ═══════════════════════════════════════════════════════════

OCR_ENGINES = {
    "pytesseract": ocr_pytesseract,
    "easyocr": ocr_easyocr,
    "rapidocr": ocr_rapidocr,
    "doctr": ocr_doctr,
    "paddleocr": ocr_paddleocr,
}


def check_engine_available(name: str) -> tuple[bool, str]:
    """Проверяет, можно ли загрузить OCR-движок (лёгкая проверка без загрузки моделей)."""
    try:
        if name == "pytesseract":
            import pytesseract
            pytesseract.get_tesseract_version()
        elif name == "easyocr":
            import easyocr  # noqa: F401
        elif name == "rapidocr":
            from rapidocr import RapidOCR  # noqa: F401
        elif name == "doctr":
            from doctr.models import ocr_predictor  # noqa: F401
        elif name == "paddleocr":
            import os
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
            from paddleocr import PaddleOCR  # noqa: F401
        else:
            return False, "Unknown"
        return True, "OK"
    except Exception as e:
        return False, str(e)[:100]


def main():
    files = sorted(TEST_DIR.glob("*.pdf"))
    if MAX_FILES > 0:
        files = files[:MAX_FILES]

    total = len(files)
    print(f"OCR Бенчмарк: {total} файлов из {TEST_DIR.name}")
    print(f"  DPI: {DPI}, Макс. страниц: {MAX_PAGES}")
    print()

    # ── Проверка доступности движков ──
    available = {}
    print("Проверка OCR-движков:")
    for name in OCR_ENGINES:
        ok, msg = check_engine_available(name)
        available[name] = ok
        status = "OK" if ok else f"НЕДОСТУПЕН ({msg})"
        print(f"  {name:<15} {status}")
    print()

    active_engines = {n: f for n, f in OCR_ENGINES.items() if available[n]}
    if not active_engines:
        print("Нет доступных OCR-движков!")
        return

    # ── Предрендер PDF → Images (один раз для всех движков) ──
    print("Рендер PDF -> изображения...")
    images_cache: dict[str, list[Image.Image]] = {}
    render_errors = []
    t_render_start = time.perf_counter()

    for i, fp in enumerate(files):
        try:
            images_cache[fp.name] = pdf_to_images(fp)
        except Exception as e:
            render_errors.append((fp.name, str(e)))
            images_cache[fp.name] = []
        if (i + 1) % 25 == 0 or (i + 1) == total:
            print(f"  [{i+1}/{total}] отрендерено")

    t_render = time.perf_counter() - t_render_start
    print(f"  Рендер завершён за {t_render:.1f}с ({len(render_errors)} ошибок)")
    print()

    # ── Прогон каждого OCR-движка ──
    results: dict[str, list[dict]] = {}

    for eng_name, eng_func in active_engines.items():
        print(f"{'='*60}")
        print(f"  Запуск: {eng_name}")
        print(f"{'='*60}")

        eng_results = []
        t_eng_start = time.perf_counter()

        for i, fp in enumerate(files):
            imgs = images_cache.get(fp.name, [])
            if not imgs:
                eng_results.append({
                    "file": fp.name,
                    "ocr_text": "",
                    "class": "render_error",
                    "time": 0.0,
                    "error": True,
                })
                continue

            t0 = time.perf_counter()
            try:
                text = eng_func(imgs)
                elapsed = time.perf_counter() - t0
                cls = classify_ocr_text(text)
                eng_results.append({
                    "file": fp.name,
                    "ocr_text": text[:200],  # фрагмент для дебага
                    "class": cls,
                    "time": elapsed,
                    "error": False,
                })
            except Exception as e:
                elapsed = time.perf_counter() - t0
                eng_results.append({
                    "file": fp.name,
                    "ocr_text": "",
                    "class": "ocr_error",
                    "time": elapsed,
                    "error": True,
                    "error_msg": str(e)[:100],
                })

            if (i + 1) % 10 == 0 or (i + 1) == total:
                t_total = time.perf_counter() - t_eng_start
                speed = (i + 1) / t_total if t_total > 0 else 0
                eta = (total - i - 1) / speed if speed > 0 else 0
                print(f"  [{i+1}/{total}] {speed:.2f} файлов/с | ETA {int(eta)}с")

        t_eng_total = time.perf_counter() - t_eng_start
        results[eng_name] = eng_results

        # Статистика движка
        n_ok = sum(1 for r in eng_results if not r["error"])
        n_bill = sum(1 for r in eng_results if r["class"] == "bill_pdf")
        n_musor = sum(1 for r in eng_results if r["class"] == "bill_musor")
        n_nokey = sum(1 for r in eng_results if r["class"] == "text_nokey")
        n_notext = sum(1 for r in eng_results if r["class"] == "no_text")
        n_err = sum(1 for r in eng_results if r["error"])
        avg_time = sum(r["time"] for r in eng_results if not r["error"]) / max(n_ok, 1)

        print(f"\n  Результат {eng_name}:")
        print(f"    Обработано:     {n_ok}/{total}")
        print(f"    bill_pdf:       {n_bill}  ({n_bill/total*100:.1f}%)")
        print(f"    bill_musor:     {n_musor}  ({n_musor/total*100:.1f}%)")
        print(f"    text_nokey:     {n_nokey}  ({n_nokey/total*100:.1f}%)")
        print(f"    no_text:        {n_notext}")
        print(f"    ошибки:         {n_err}")
        print(f"    Среднее время:  {avg_time:.3f}с/файл")
        print(f"    Общее время:    {t_eng_total:.1f}с")
        print()

    # ═══════════════════════════════════════════════════════
    #  Сводная таблица
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*75}")
    print(f"  СВОДНАЯ ТАБЛИЦА OCR БЕНЧМАРКА")
    print(f"{'='*75}")
    print(f"  Файлов: {total}, DPI: {DPI}, Макс. страниц: {MAX_PAGES}")
    print()

    # Подсчитаем % файлов, где OCR нашёл ключевые слова (bill_pdf + bill_musor)
    # Это и есть "полезность" OCR — сколько файлов из nokey он бы переклассифицировал
    header = f"  {'Движок':<15} {'Найдено':>8} {'bill_pdf':>10} {'bill_musor':>11} {'nokey':>8} {'Ср.время':>10} {'Общее':>8}"
    print(header)
    print(f"  {'-'*72}")

    summary_rows = []
    for eng_name, eng_results in results.items():
        n_bill = sum(1 for r in eng_results if r["class"] == "bill_pdf")
        n_musor = sum(1 for r in eng_results if r["class"] == "bill_musor")
        n_nokey = sum(1 for r in eng_results if r["class"] == "text_nokey")
        n_found = n_bill + n_musor
        n_ok = sum(1 for r in eng_results if not r["error"])
        avg_t = sum(r["time"] for r in eng_results if not r["error"]) / max(n_ok, 1)
        total_t = sum(r["time"] for r in eng_results)
        pct = n_found / total * 100

        summary_rows.append((eng_name, n_found, pct, n_bill, n_musor, n_nokey, avg_t, total_t))

    # Сортировка: больше найденных — лучше
    summary_rows.sort(key=lambda x: (-x[1], x[6]))

    for name, n_found, pct, n_bill, n_musor, n_nokey, avg_t, total_t in summary_rows:
        print(f"  {name:<15} {n_found:>5} ({pct:>4.1f}%) {n_bill:>10} {n_musor:>11} {n_nokey:>8} {avg_t:>9.3f}с {total_t:>7.1f}с")

    # ── Рейтинг качество/скорость ──
    print(f"\n  Рейтинг (качество * скорость):")
    print(f"  {'Движок':<15} {'Найдено%':>9} {'Ср.время':>10} {'Score':>8}")
    print(f"  {'-'*45}")

    for name, n_found, pct, n_bill, n_musor, n_nokey, avg_t, total_t in summary_rows:
        # Score: % найденных / время (больше = лучше)
        score = pct / max(avg_t, 0.001)
        print(f"  {name:<15} {pct:>8.1f}% {avg_t:>9.3f}с {score:>8.1f}")

    # ── Сохраняем детальные результаты в CSV ──
    csv_path = Path(__file__).parent / "benchmark_ocr_results.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("engine,file,class,time_sec,error,text_preview\n")
        for eng_name, eng_results in results.items():
            for r in eng_results:
                text_prev = r.get("ocr_text", "").replace('"', "'").replace("\n", " ")[:100]
                f.write(f'{eng_name},"{r["file"]}",{r["class"]},{r["time"]:.4f},{r["error"]},"{text_prev}"\n')
    print(f"\n  Детальные результаты: {csv_path}")


if __name__ == "__main__":
    main()
