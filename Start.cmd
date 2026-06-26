@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Python environment not found. Run Install.cmd first.
  echo.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0archive_pdf.py" --queue-review
echo.
echo Opening manual review window...
"%~dp0.venv\Scripts\python.exe" "%~dp0archive_pdf.py" --review-gui
echo.
pause
