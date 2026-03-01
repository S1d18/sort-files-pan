@echo off

:: Задаём переменные для путей
set "BASE_DIR=D:\python\Sort_files_pan"
set "PYTHON=%BASE_DIR%\venv\Scripts\python.exe"

:: Переход в папку
cd /D "%BASE_DIR%"

:: Запуск скриптов
"%PYTHON%" main.py
"%PYTHON%" tg.py

:: call "%BASE_DIR%\tg.bat"

pause