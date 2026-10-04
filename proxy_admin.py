"""硒游记 · 商品管理后台专用反向代理。

监听 127.0.0.1:8002，只把「管理端需要的路径」转发给主服务 127.0.0.1:8001：
    /admin                   管理端页面
    /assets/*                管理端用到的品牌与框架素材
    /uploads/*               商品图片
    /api/scenes              场景下拉框
    /api/products(/id)       商品列表与详情（管理端表格用）
    /api/admin/*             管理端全部读写接口
    /api/health              健康检查
其他一切路径（前台首页 /api/chat 等）一律 403，
所以这条隧道拿到的地址无法用来访问或滥用前台应用。

启动：
    .venv\\Scripts\\python.exe -m uvicorn proxy_admin:app --host 127.0.0.1 --port 8002
"""

from __future__ import annotations

import os
import re

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

UPSTREAM = os.getenv("ADMIN_PROXY_UPSTREAM", "http://127.0.0.1:8001").rstrip("/")

ALLOW_EXACT = {"/admin", "/api/health", "/api/scenes"}
ALLOW_PREFIX = ("/assets/", "/uploads/", "/api/admin/")
ALLOW_PRODUCTS = re.compile(r"^/api/products(/\d+)?$")

# 逐跳首部 + 长度/编码相关首部：由 httpx 与本次响应自行决定，不能原样透传
STRIP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "accept-encoding",
    "content-encoding",
}

app = FastAPI(title="Xiyouji admin-only proxy", docs_url=None, redoc_url=None, openapi_url=None)


def is_allowed(path: str) -> bool:
    if path in ALLOW_EXACT:
        return True
    if path.startswith(ALLOW_PREFIX):
        return True
    return bool(ALLOW_PRODUCTS.match(path))


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=302)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
)
async def relay(path: str, request: Request) -> Response:
    full = "/" + path
    if not is_allowed(full):
        return JSONResponse(
            {"error": "此入口仅用于硒游记商品管理后台", "path": full},
            status_code=403,
        )

    headers = {k: v for k, v in request.headers.items() if k.lower() not in STRIP_HEADERS}
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            upstream = await client.request(
                request.method,
                UPSTREAM + full,
                headers=headers,
                content=body,
                params=request.query_params,
            )
    except httpx.HTTPError:
        return JSONResponse({"error": "主服务暂时不可用，请确认本机 8001 正在运行"}, status_code=502)

    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in STRIP_HEADERS}
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=upstream.headers.get("content-type"),
    )
