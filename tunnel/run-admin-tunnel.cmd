@echo off
rem ============================================================
rem  Xiyouji ADMIN tunnel supervisor
rem  Keeps a second Cloudflare quick tunnel alive, pointing at
rem  the admin-only proxy on 127.0.0.1:8002.
rem  The public URL is written into admin-tunnel.log (show-admin-url.cmd).
rem ============================================================
setlocal
set ROOT=C:\Users\13917\xiyouji-localapp
set LOG=%ROOT%\tunnel\admin-tunnel.log
set CF="C:\Program Files (x86)\cloudflared\cloudflared.exe"

if not exist "%ROOT%\tunnel" mkdir "%ROOT%\tunnel"

rem singleton guard: the PUBLIC tunnel keeps exactly one cloudflared alive.
rem If two or more are already running, this admin tunnel is up -> exit.
set N=0
for /f %%c in ('tasklist /FI "IMAGENAME eq cloudflared.exe" ^| find /C /I "cloudflared.exe"') do set N=%%c
if %N% GEQ 2 (
  echo ==== %DATE% %TIME% admin tunnel already running, supervisor exits ==== >> "%LOG%"
  exit /b 0
)

echo ==== %DATE% %TIME% admin tunnel supervisor started ==== >> "%LOG%"

:loop
rem rotate log if bigger than ~8 MB
for %%A in ("%LOG%") do if %%~zA GTR 8000000 del "%LOG%"

echo. >> "%LOG%"
echo ==== %DATE% %TIME% starting admin cloudflared -> http://127.0.0.1:8002 ==== >> "%LOG%"
%CF% tunnel --url http://127.0.0.1:8002 --no-autoupdate >> "%LOG%" 2>&1
echo ==== %DATE% %TIME% admin cloudflared exited (code %ERRORLEVEL%), restart in 10s ==== >> "%LOG%"

ping -n 11 127.0.0.1 >nul
goto loop
