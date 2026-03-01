@echo off
setlocal enabledelayedexpansion

REM === 1) Выбор Python ===
REM Пытаемся использовать "py" лаунчер (Windows), иначе "python"
set PY=py -3
%PY% -V >nul 2>&1
if errorlevel 1 (
  set PY=python
  %PY% --version >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Python не найден. Установите Python 3.10+ и запустите батник снова.
    echo Скачать: https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
)

REM === 2) Создаём виртуальное окружение ===
if not exist venv (
  echo [INFO] Создаю виртуальное окружение venv ...
  %PY% -m venv venv
  if errorlevel 1 (
    echo [ERROR] Не удалось создать venv.
    pause
    exit /b 1
  )
)

REM === 3) Активируем venv ===
call venv\Scripts\activate.bat
if errorlevel 1 (
  echo [ERROR] Не удалось активировать venv.
  pause
  exit /b 1
)

REM === 4) Обновляем pip и ставим зависимости ===
python -m pip install --upgrade pip
if exist requirements.txt (
  echo [INFO] Ставлю зависимости из requirements.txt ...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Ошибка установки зависимостей.
    pause
    exit /b 1
  )
) else (
  echo [WARN] requirements.txt не найден — пропускаю установку пакетов.
)

endlocal
