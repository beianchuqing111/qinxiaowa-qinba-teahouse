@echo off
rem ============================================================
rem  Xiyouji local web service supervisor (FastAPI / uvicorn :8001)
rem  Starts at boot and restarts the service if it crashes.
rem  If port 8001 is already in use, it exits and does nothing.
rem ============================================================
setlocal
set ROOT=C:\Users\13917\xiyouji-localapp
set LOG=%ROOT%\tunnel\server.log
cd /d "%ROOT%"

if not exist "%ROOT%\tunnel" mkdir "%ROOT%\tunnel"
echo ==== %DATE% %TIME% supervisor started ==== >> "%LOG%"

netstat -ano | findstr "LISTENING" | findstr ":8001" >nul 2>&1
if %ERRORLEVEL%==0 (
  echo ==== %DATE% %TIME% port 8001 already in use, supervisor exits ==== >> "%LOG%"
  exit /b 0
)

:loop
for %%A in ("%LOG%") do if %%~zA GTR 8000000 del "%LOG%"
echo. >> "%LOG%"
echo ==== %DATE% %TIME% starting uvicorn ==== >> "%LOG%"
"%ROOT%\.venv\Scripts\uvicorn.exe" app:app --host 0.0.0.0 --port 8001 >> "%LOG%" 2>&1
echo ==== %DATE% %TIME% uvicorn exited (code %ERRORLEVEL%), restart in 10s ==== >> "%LOG%"
ping -n 11 127.0.0.1 >nul
goto loop
