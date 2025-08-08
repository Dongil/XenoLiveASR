@echo off
setlocal

:: =================================================================
:: 실시간 음성인식 번역 서버 실행 스크립트 (Production Mode)
:: =================================================================

:: !! 실행 환경을 'production'으로 설정 !!
set APP_ENV=production

cd /d "%~dp0"

echo.
echo =============================================================
echo   LiveWhisper Server for Xenoglobal
echo =============================================================
echo.

IF NOT EXIST .\.venv\Scripts\activate (
    echo [ERROR] Virtual environment (.venv) not found.
    pause
    exit /b 1
)

call .\.venv\Scripts\activate

python main.py %*

echo.
echo Server process has been terminated.
pause
endlocal