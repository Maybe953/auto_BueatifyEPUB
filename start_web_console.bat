@echo off
chcp 65001 >nul
title EPUB Auto-Beautifier Web Console
echo ===================================================
echo       EPUB Auto-Beautifier Web Console Starter
echo ===================================================
echo [*] Activating virtual environment (venv)...
call .\venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate venv! Please check if venv directory exists.
    pause
    exit /b
)
echo [*] Starting Web service and opening browser...
python main.py --web
pause
