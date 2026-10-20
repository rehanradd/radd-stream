@echo off
REM run.bat — Windows launcher for radd-stream
REM Usage: run.bat [command] [args]
REM Examples:
REM   run.bat sync
REM   run.bat fetch "https://multimovies.garden/movie/pathaan-2023/"
REM   run.bat stats

SETLOCAL
SET SCRIPT_DIR=%~dp0
SET FF_DIR=%SCRIPT_DIR%Fast_Fetch

where python >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python not found. Download from https://python.org
    pause
    exit /b 1
)

echo [radd-stream] Running: python %FF_DIR%\fast_fetch.py %*
echo.

python "%FF_DIR%\fast_fetch.py" %*
ENDLOCAL
