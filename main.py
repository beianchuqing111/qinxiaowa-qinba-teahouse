"""FastAPI 应用入口。

启动顺序：加载配置 → 装配容器 → 预加载资料库（提前暴露数据问题）→ 绑定路由。
推荐直接 `python run.py` 或 `uvicorn app.main:app --reload`。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.deps import Container
from app.api.routes import catalog, health, outbound, recommend
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging

logger = logging.getLogger("qinba.main")


def _preload(container: Container) -> None:
    """预加载资料库：宁可启动时就报错，也不要演示中途才发现数据有问题。"""
    try:
        stats = container.catalog.stats()
        logger.info(
            "资料库就绪 backend=%s 商品 %d 款（已审核 %d 款）路径=%s",
            stats["backend"],
            stats["total"],
            stats["approved"],
            stats["path"],
        )
        if stats["approved"] == 0:
            logger.warning("没有任何已审核商品，推荐接口会返回明确提示而不是编造内容")
    except Exception as exc:  # noqa: BLE001 - 启动阶段只提示，不阻断进程
        logger.error("资料库预加载失败：%s", exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建应用。传入 settings 即可用于测试或多环境部署。"""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging("DEBUG" if settings.debug else "INFO")
        container: Container = app.state.container

        _preload(container)
        await container.startup()
        if container.settings.llm_ready:
            logger.info("大模型已接入：仅用于改写对白，所有输出都会经过事实护栏")
        else:
            logger.info("大模型未启用：对白使用内置模板，功能完整可演示")
        logger.info("接口文档：http://127.0.0.1:%s/docs", container.settings.app_port)
        try:
            yield
        finally:
            await container.shutdown()
            logger.info("服务已关闭")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "黑客松企业赛道 · 秦小娲的秦巴茶舍（首期最小可演示方案）后端服务。\n\n"
            "职责边界：需求识别 · 已审核商品筛选 · 受约束推荐 · 对白与推荐理由 · 事实与内容安全。\n"
            "前端负责茶舍体验、角色呈现与操作反馈。"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 容器在这里就挂上，保证 lifespan 之外（如测试直接调接口）也能取到
    app.state.container = Container(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(catalog.router, prefix="/api")
    app.include_router(catalog.option_router, prefix="/api")
    app.include_router(recommend.router, prefix="/api")
    app.include_router(outbound.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def index() -> dict:
        return {
            "service": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": "/api/health",
            "endpoints": [
                "GET  /api/health",
                "GET  /api/health/detail",
                "GET  /api/products",
                "GET  /api/products/{product_id}",
                "GET  /api/scenes",
                "POST /api/recommend",
                "POST /api/recommend/another",
                "POST /api/recommend/greeting",
                "GET  /api/outbound/{product_id}",
                "GET  /api/outbound/{product_id}/check",
            ],
        }

    return app


app = create_app()
