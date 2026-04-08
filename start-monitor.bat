@echo off
title Audio Monitor - Rode NT USB+
cd /d "%~dp0"
pip install -r requirements.txt --quiet 2>nul
python monitor.py
pause
