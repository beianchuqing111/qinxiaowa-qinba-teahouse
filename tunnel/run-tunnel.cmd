@echo off
rem ============================================================
rem  Xiyouji public tunnel supervisor
rem  Keeps the Cloudflare quick tunnel to 127.0.0.1:8001 alive.
rem  The public URL is written into tunnel.log (see show-url.cmd).
rem ============================================================
setlocal
set ROOT=C:\Users\13917\xiyouji-localapp
set LOG=%ROOT%\tunnel\tunnel.log
set CF="C:\Program Files (x86)\cloudflared\cloudflared.exe"

if not exist "%ROOT%\tunnel" mkdir "%ROOT%\tunnel"

rem singleton guard: do nothing if a cloudflared is already running
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | findstr /I "cloudflared.exe" >nul
if %ERRORLEVEL%==0 (
  echo ==== %DATE% %TIME% cloudflared already running, supervisor exits ==== >> "%LOG%"
  exit /b 0
)

echo ==== %DATE% %TIME% supervisor started ==== >> "%LOG%"

:loop
rem rotate log if bigger than ~8 MB
for %%A in ("%LOG%") do if %%~zA GTR 8000000 del "%LOG%"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% starting cloudflared ==== >> "%LOG%"
%CF% tunnel --url http://127.0.0.1:8001 --no-autoupdate >> "%LOG%" 2>&1
echo ==== %DATE% %TIME% cloudflared exited (code %ERRORLEVEL%), restart in 10s ==== >> "%LOG%"

rem wait 10s (ping works in non-interactive sessions, timeout does not)
ping -n 11 127.0.0.1 >nul
goto loop
