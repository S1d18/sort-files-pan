# Sort Files Pan
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Автоматический сортировщик PDF и изображений с классификацией по содержимому.

## Возможности

- Автоматическое определение типа файла по magic-сигнатуре
- Сортировка изображений в отдельные папки
- Классификация PDF по содержимому (счета, билеты, товары и др.)
- OCR для PDF без текстового слоя (Tesseract)
- Обработка запароленных и битых PDF
- Многопроцессорная обработка
- Уведомления в Telegram по завершении

## Технологии

- Python 3
- PyPDF2 / pdfminer.six / PyMuPDF — извлечение текста из PDF
- pdf-parse (Node.js) — альтернативный парсер
- Tesseract OCR — распознавание текста
- tqdm — прогресс-бар
- multiprocessing — параллельная обработка

## Установка

```bash
git clone https://github.com/<username>/sort-files-pan.git
cd sort-files-pan
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
pip install -r requirements.txt
npm install  # для pdf-parse
```

## Настройка

```bash
export TELEGRAM_BOT_TOKEN=your-token
export TELEGRAM_CHAT_ID=your-chat-id
```

Пути настраиваются в `config.py`:
- `ROOTS_GLOB` — шаблон пути к исходным файлам

## Использование

```bash
python main.py
```

Или через батник:
```bash
Start sort.cmd
```

## Структура проекта

| Файл | Описание |
|------|----------|
| `main.py` | Основной оркестратор |
| `config.py` | Настройки, пути, ключевые слова |
| `run_type.py` | Определение типа файла |
| `run_images.py` | Сортировка изображений |
| `run_pdfs_multi.py` | Классификация PDF (многопроцессорная) |
| `run_textnokey.py` | OCR для PDF без текста |
| `mover.py` | Безопасное перемещение файлов |
| `tg.py` | Telegram-уведомления |
