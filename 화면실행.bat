@echo off
rem Start the Streamlit screen (app.py) from this folder.
cd /d "%~dp0"
chcp 65001 > nul
set PYTHONUTF8=1
python -m streamlit run app.py
pause
