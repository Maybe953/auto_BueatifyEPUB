@echo off
chcp 65001 >nul
title EPUB Auto-Beautifier Terminal Launcher
echo ===================================================
echo   Starting PowerShell terminal with venv activated...
echo ===================================================
start powershell.exe -NoExit -Command "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process; if (Test-Path '.\venv\Scripts\Activate.ps1') { . .\venv\Scripts\Activate.ps1 }"
