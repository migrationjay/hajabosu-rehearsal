@echo off
rem Run the inbox batch (run.py) from this folder.
cd /d "%~dp0"
chcp 65001 > nul
set PYTHONUTF8=1
python run.py
pause
