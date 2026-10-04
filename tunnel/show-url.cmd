@echo off
rem Print the current public tunnel URL, and save it to current-url.txt
setlocal
set ROOT=C:\Users\13917\xiyouji-localapp
set LOG=%ROOT%\tunnel\tunnel.log
if not exist "%LOG%" (
  echo tunnel.log not found - the tunnel may never have started
  exit /b 1
)
powershell -NoProfile -Command "$m = Select-String -Path '%LOG%' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1; if ($m) { $u = $m.Matches.Value; $u; Set-Content -Path '%ROOT%\tunnel\current-url.txt' -Value $u -Encoding UTF8 } else { Write-Output 'no tunnel URL found in log yet' }"
