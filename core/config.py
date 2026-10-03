"""全局配置。

所有可调参数集中在此处，通过环境变量或 .env 覆盖。
原则：默认配置必须能"零配置启动"并完整跑通演示闭环
（大模型关闭、外链留空），避免演示现场依赖外部服务。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：app/core/config.py -> app/core -> app -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """服务配置。字段名对应环境变量大写形式。"""

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 基础 ----------
    app_env: str = "dev"
    app_name: str = "秦小娲的秦巴茶舍 · 后端服务"
    app_version: str = "1.0.0"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # ---------- 商品资料库 ----------
    # json | sqlite
    catalog_backend: str = "json"
    catalog_json_path: str = "app/data/products.seed.json"
    catalog_sqlite_path: str = "app/data/teahouse.db"

    # ---------- 安全外链 ----------
    # 允许跳转的商铺域名白名单；为空表示"未接入真实店铺"
    shop_link_allowed_hosts: list[str] = Field(default_factory=list)
    # 外链校验超时（秒）：仅用于可选的可达性探测，不阻塞主流程
    link_probe_timeout_seconds: float = 3.0

    # ---------- 可选大模型 ----------
    llm_enabled: bool = False
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 6.0
    llm_max_retries: int = 1
    llm_max_output_chars: int = 220

    # ---------- 会话 ----------
    session_ttl_seconds: int = 1800
    session_max_entries: int = 5000

    # ---------- 输入边界（防止前端误传超大内容）----------
    max_preference_chars: int = 60
    max_recipient_chars: int = 20

    @field_validator("cors_allow_origins", "shop_link_allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """支持 CORS_ALLOW_ORIGINS=a,b 这种逗号分隔写法。"""
        if value is None or isinstance(value, str):
            raw = value or ""
            items = [item.strip() for item in raw.split(",")]
            items = [item for item in items if item]
            if items:
                return items
            return ["*"] if raw.strip() == "*" else []
        return value

    @field_validator("catalog_backend", mode="before")
    @classmethod
    def _normalize_backend(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized not in {"json", "sqlite"}:
                raise ValueError("CATALOG_BACKEND 只能是 json 或 sqlite")
            return normalized
        return value

    # ---------- 路径工具 ----------
    def resolve_path(self, raw: str) -> Path:
        """相对路径按项目根目录解析，保证任意工作目录下都能启动。"""
        path = Path(raw)
        return path if path.is_absolute() else (PROJECT_ROOT / path)

    @property
    def catalog_path(self) -> Path:
        if self.catalog_backend == "sqlite":
            return self.resolve_path(self.catalog_sqlite_path)
        return self.resolve_path(self.catalog_json_path)

    @property
    def llm_ready(self) -> bool:
        """是否具备真正调用大模型的条件。"""
        return bool(self.llm_enabled and self.llm_api_key and self.llm_base_url)

    @property
    def allowed_host_set(self) -> set[str]:
        return {host.strip().lower() for host in self.shop_link_allowed_hosts if host.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
