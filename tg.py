#!/usr/bin/env python3
# telegram_send.py
# Отправка сообщения в Telegram (аналог вашего tg.bat)
# Токен и chat_id берём из переменных окружения или (опционально) из config.py

import os
import sys
import json
import urllib.parse
import urllib.request
from config import Massage_TG

def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    if not token or not chat_id:
        raise ValueError("TOKEN и CHAT_ID не заданы.")
    base = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
    }
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(base, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")

def main():
    # 1) пробуем импортировать из config.py (если у тебя общий конфиг)
    TOKEN = None
    CHAT_ID = None
    try:
        import config  # ваш единый конфиг проекта
        TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        CHAT_ID = getattr(config, "TELEGRAM_CHAT_ID", None)
    except Exception:
        pass

    # 2) если нет в config.py, читаем из переменных окружения
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", TOKEN)
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", CHAT_ID)

    # 3) текст сообщения берём из аргумента или дефолт
    message = Massage_TG
    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])

    try:
        send_telegram_message(TOKEN, CHAT_ID, message)
        print("Сообщение отправлено.")
    except Exception as e:
        print(f"Ошибка отправки: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
