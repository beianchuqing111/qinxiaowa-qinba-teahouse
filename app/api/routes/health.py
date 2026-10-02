"""健康检查与自检。

演示前先访问 /api/health，一眼确认：资料库读到了几款、过审几款、
大模型开没开、外链白名单配置了几个域名。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import Container, container_of
from app.models.api_schemas import HealthResponse

router = APIRouter(tags=["健康检查"])


@router.get("/health", response_model=HealthResponse, summary="服务健康与配置自检")
def health(container: Container = Depends(container_of)) -> HealthResponse:
    settings = container.settings
    stats = container.catalog.stats()
    return HealthResponse(
        status="ok" if stats["approved"] > 0 else "degraded",
        version=__version__,
        env=settings.app_env,
        catalog_backend=stats["backend"],
        catalog_ready=stats["approved"] > 0,
        approved_product_count=stats["approved"],
        llm_enabled=settings.llm_enabled,
        llm_ready=settings.llm_ready,
        outbound_link_whitelist=container.link_guard.whitelist,
    )


@router.get("/health/detail", summary="详细自检（含资料库路径与降级信息）")
def health_detail(container: Container = Depends(container_of)) -> dict:
    return {
        "catalog": container.catalog.stats(),
        "sessions": container.sessions.stats(),
        "llm": {
            "enabled": container.settings.llm_enabled,
            "ready": container.settings.llm_ready,
            "model": container.settings.llm_model if container.settings.llm_ready else None,
            "timeout_seconds": container.settings.llm_timeout_seconds,
        },
        "outbound": {
            "whitelist": container.link_guard.whitelist,
            "policy": "仅白名单内 https 链接允许跳转，其余一律按未接入处理",
        },
        "config": {
            "catalog_backend": container.settings.catalog_backend,
            "catalog_path": str(container.settings.catalog_path),
            "llm_max_output_chars": container.settings.llm_max_output_chars,
        },
    }
