@echo off
REM ── Build do FinaHub (.EXE) ──────────────────────────────────────
REM Requisitos: pip install pyinstaller  (alem do requirements.txt)
cd /d "%~dp0"

pyinstaller --noconfirm --clean --onefile --windowed ^
  --name "FinaHub" ^
  --add-data "config.json;." ^
  --collect-all customtkinter ^
  --paths "finahub\vendor\remessa_v3" ^
  --hidden-import services ^
  --hidden-import services.parsers ^
  --hidden-import services.reconciler ^
  --hidden-import services.exporter ^
  --hidden-import services.excel_reader ^
  --hidden-import core ^
  --hidden-import core.utils ^
  --hidden-import core.logger ^
  --hidden-import core.session ^
  --hidden-import core.theme ^
  --hidden-import ui ^
  --hidden-import ui.main_window ^
  --hidden-import ui.dashboard ^
  --hidden-import ui.attention_table ^
  --hidden-import ui.widgets ^
  --hidden-import openpyxl ^
  --hidden-import rapidfuzz ^
  --hidden-import xlrd ^
  main.py

echo.
echo ── Build concluido. O executavel esta em dist\"FinaHub.exe" ──
pause
