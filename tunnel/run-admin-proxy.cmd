@echo off
rem ============================================================
rem  Xiyouji admin console proxy supervisor
rem  Serves the admin-only reverse proxy on 127.0.0.1:8002.
rem  The dedicated admin tunnel points at this port.
rem ============================================================
setlocal
set ROOT=C:\Users\13917\xiyouji-localapp
set LOG=%ROOT%\tunnel\admin-proxy.log
set PY=%ROOT%\.venv\Scripts\python.exe

if not exist "%ROOT%\tunnel" mkdir "%ROOT%\tunnel"

rem singleton guard: do nothing if 8002 is already listening
netstat -ano | findstr "LISTENING" | findstr ":8002 " >nul
if %ERRORLEVEL%==0 (
  echo ==== %DATE% %TIME% port 8002 already in use, admin proxy supervisor exits ==== >> "%LOG%"
  exit /b 0
)

echo ==== %DATE% %TIME% admin proxy supervisor started ==== >> "%LOG%"

:loop
rem rotate log if bigger than ~8 MB
for %%A in ("%LOG%") do if %%~zA GTR 8000000 del "%LOG%"

echo ==== %DATE% %TIME% starting admin proxy on 127.0.0.1:8002 ==== >> "%LOG%"
cd /d "%ROOT%"
"%PY%" -m uvicorn proxy_admin:app --host 127.0.0.1 --port 8002 >> "%LOG%" 2>&1
echo ==== %DATE% %TIME% admin proxy exited (code %ERRORLEVEL%), restart in 10s ==== >> "%LOG%"

rem wait 10s (ping works in non-interactive sessions, timeout does not)
ping -n 11 127.0.0.1 >nul
goto loop
