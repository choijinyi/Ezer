@echo off
chcp 65001 >nul
cd /d "%~dp0"
python build_book.py
pause
