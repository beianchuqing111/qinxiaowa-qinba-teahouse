"""依赖装配。

手工构造函数注入，不引入额外 DI 框架：依赖关系一眼可见，
也方便测试时整体替换（如把资料库换成假数据）。
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from app.core.config import Settings, get_settings
from app.core.security import ShopLinkGuard
from app.data.repository import CatalogRepository
from app.services.dialogue import DialogueService
from app.services.intent import IntentService
from app.services.llm import LlmClient
from app.services.recommender import Recommender
from app.services.session import SessionStore
from app.services.teahouse import TeahouseService


class Container:
    """应用级单例集合，在 lifespan 里构造并挂到 app.state。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.catalog = CatalogRepository(self.settings)
        self.link_guard = ShopLinkGuard(self.settings)
        self.sessions = SessionStore(self.settings)
        self.llm = LlmClient(self.settings)
        self.intent = IntentService(self.settings)
        self.recommender = Recommender(self.settings)
        self.dialogue = DialogueService(self.settings, self.llm)
        self.teahouse = TeahouseService(
            settings=self.settings,
            catalog=self.catalog,
            intent_service=self.intent,
            recommender=self.recommender,
            dialogue=self.dialogue,
            sessions=self.sessions,
            link_guard=self.link_guard,
        )

    async def startup(self) -> None:
        await self.llm.startup()

    async def shutdown(self) -> None:
        await self.llm.shutdown()


@lru_cache
def get_container() -> Container:
    return Container()


def container_of(request: Request) -> Container:
    """优先取 lifespan 注入的实例，测试中未注入时退回模块级单例。"""
    existing = getattr(request.app.state, "container", None)
    if isinstance(existing, Container):
        return existing
    return get_container()


def get_teahouse(request: Request) -> TeahouseService:
    return container_of(request).teahouse


def get_catalog(request: Request) -> CatalogRepository:
    return container_of(request).catalog


def get_settings_dep(request: Request) -> Settings:
    return container_of(request).settings
