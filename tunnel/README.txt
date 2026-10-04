Xiyouji tunnels - how it works
==============================

Two separate public entry points
--------------------------------
1) PUBLIC site tunnel   -> http://127.0.0.1:8001
   The consumer-facing app: map tour, 秦小娲 digital-human chat, product cards.
   Created by run-tunnel.cmd  /  URL logged in tunnel.log

2) ADMIN console tunnel -> http://127.0.0.1:8002  (admin-only, path filtered)
   Created by run-admin-tunnel.cmd  /  URL logged in admin-tunnel.log
   Port 8002 is served by proxy_admin.py, which forwards ONLY:
       /                     -> 302 redirect to /admin
       /admin                admin console page
       /assets/*  /uploads/* brand art and product photos
       /api/scenes  /api/products(/id)  /api/health
       /api/admin/*          all admin read/write endpoints
   Everything else (the public homepage, /api/chat, ...) returns 403,
   so the admin link can never be used to browse or abuse the public app.

Files in this folder
--------------------
run-server.cmd         supervisor for the local FastAPI/uvicorn service (:8001)
run-tunnel.cmd         supervisor for the PUBLIC cloudflared -> :8001
run-admin-proxy.cmd    supervisor for the admin-only proxy (uvicorn :8002)
run-admin-tunnel.cmd   supervisor for the ADMIN cloudflared -> :8002
show-url.cmd           prints the public URL, saves it to current-url.txt
show-admin-url.cmd     prints the admin URL, saves it to admin-url.txt
tunnel.log             public cloudflared output
admin-tunnel.log       admin cloudflared output
admin-proxy.log        admin proxy (uvicorn) output
server.log             uvicorn output
current-url.txt        last known PUBLIC url
admin-url.txt          last known ADMIN url

All four supervisors run an endless loop: if their process dies they restart it
after 10 seconds, so a network blip does not take the site down permanently.

Autostart
---------
Four logon scripts are placed in:
  %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
    xiyouji-server.vbs        -> run-server.cmd       (hidden)
    xiyouji-tunnel.vbs        -> run-tunnel.cmd       (hidden)
    xiyouji-admin-proxy.vbs   -> run-admin-proxy.cmd  (hidden)
    xiyouji-admin-tunnel.vbs  -> run-admin-tunnel.cmd (hidden)

So after a reboot: log in, and service + both tunnels come back by themselves.
No console windows stay visible.

Admin console login
-------------------
Open the admin URL (it lands straight on /admin) and paste the token from .env:
    ADMIN_TOKEN=<见本机 .env 中的 ADMIN_TOKEN，不要写进仓库>
The token is sent as the X-Admin-Token request header.
IMPORTANT: the admin console is now reachable from the public internet, so the
token above is the ONLY thing protecting it. Replace it with a long random
string in .env before sharing the admin link with anyone else.

How to get the current URLs
---------------------------
  C:\Users\13917\xiyouji-localapp\tunnel\show-url.cmd        (public)
  C:\Users\13917\xiyouji-localapp\tunnel\show-admin-url.cmd  (admin)
or open tunnel.log / admin-tunnel.log and search for "trycloudflare.com".

Important limitations
---------------------
* These are Cloudflare QUICK tunnels: the URL is random and CHANGES every time
  cloudflared restarts (reboot, crash, network drop, killing the process).
  The link only stays stable while the process keeps running.
  -> After every reboot both links change; re-run the show-url scripts.
* For a URL that never changes you need a named tunnel + your own domain
  on Cloudflare, or an ngrok/Tailscale account. Ask the assistant if you want
  to switch.
* FlClash TUN mode intercepts all traffic and WILL break the tunnels.
  Keep TUN off (system proxy is fine) while these services run.
* The PC must stay powered on and awake; everything is served from this machine.

Manual control
--------------
Stop everything:  taskkill /IM cloudflared.exe /F   (also kills both supervisor loops)
                  taskkill /IM python.exe /F       (careful: kills other python too)
Stop one tunnel:  use Task Manager, end the cloudflared whose command line
                  contains :8002 (admin) or :8001 (public).
Restart:          double-click the vbs files in the Startup folder, or run the
                  run-*.cmd files directly.
Remove autostart: delete the four .vbs files from the Startup folder.
