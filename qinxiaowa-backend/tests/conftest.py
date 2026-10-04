"""测试夹具。

测试一律使用独立的 Settings + 独立应用实例，不依赖开发者的 .env，
保证 CI 与本地结果一致。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

SEED_JSON = ROOT / "app" / "data" / "products.seed.json"


def make_settings(**overrides: Any) -> Settings:
    """构造测试用配置。默认：JSON 资料库、大模型关闭、外链白名单为空。"""
    base: dict[str, Any] = {
        "app_env": "test",
        "catalog_backend": "json",
        "catalog_json_path": str(SEED_JSON),
        "shop_link_allowed_hosts": [],
        "llm_enabled": False,
        "app_port": 8765,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    return make_settings


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def whitelist_client():
    """已接入店铺的环境：item.taobao.com 在白名单内。"""
    with TestClient(create_app(make_settings(shop_link_allowed_hosts=["item.taobao.com"]))) as test_client:
        yield test_client


@pytest.fixture
def container(settings: Settings):
    from app.api.deps import Container

    return Container(settings)
