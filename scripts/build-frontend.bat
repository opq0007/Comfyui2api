@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-frontend.ps1" %*
set "exit_code=%ERRORLEVEL%"

if not "%exit_code%"=="0" (
  echo.
  echo Frontend build failed. Exit code: %exit_code%
  pause
)

exit /b %exit_code%
