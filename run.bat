@echo off
setlocal
cd /d "%~dp0"
set "APP_DIR=%~dp0"

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%APP_DIR%app.py" %*
    exit
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%APP_DIR%app.py" %*
    exit
)

where py >nul 2>nul
if not errorlevel 1 (
    start "" py -3 "%APP_DIR%app.py" %*
    exit
)

where python >nul 2>nul
if not errorlevel 1 (
    start "" python "%APP_DIR%app.py" %*
    exit
)

echo [錯誤] 找不到 Python 執行環境，請確認已安裝 Python 並加入 PATH。
pause
exit /b 1
