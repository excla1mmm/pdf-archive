@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Python environment not found. Run Install.cmd first.
  echo.
  pause
  exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -c "import yaml, fitz, PIL, pypdf, pytesseract, requests, zxingcpp" >nul 2>nul
if errorlevel 1 (
  echo Python dependencies are missing or incomplete.
  echo Run Install.cmd first. If this keeps happening, delete the .venv folder and run Install.cmd again.
  echo.
  pause
  exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0archive_pdf.py" --queue-review
if errorlevel 1 (
  echo.
  echo Processing failed. Review window was not opened.
  echo Fix the error above and run Start.cmd again.
  echo.
  pause
  exit /b 1
)

echo.
echo Opening manual review window...
"%~dp0.venv\Scripts\python.exe" "%~dp0archive_pdf.py" --review-gui
if errorlevel 1 (
  echo.
  echo Review window failed.
  echo.
  pause
  exit /b 1
)
echo.
pause
