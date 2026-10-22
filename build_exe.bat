@echo off
rem Builds dist\ZhiaLianQuestBrowser.exe. Needs Python 3.10-3.13 from python.org.
rem Extra options are passed to build.py, for example: build_exe.bat --onedir
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

if not exist ".venv\Scripts\python.exe" (
  echo Creating a virtual environment...
  %PY% -m venv .venv || goto :fail
)
call ".venv\Scripts\activate.bat" || goto :fail

echo Installing build tools...
python -m pip install --quiet --upgrade pip || goto :fail
python -m pip install --quiet -r requirements.txt -r requirements-build.txt || goto :fail

python build.py %* || goto :fail

echo.
echo Done. Your app is dist\ZhiaLianQuestBrowser.exe
pause
exit /b 0

:fail
echo.
echo The build stopped with an error. The messages above say what went wrong.
pause
exit /b 1
