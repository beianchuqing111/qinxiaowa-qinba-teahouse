"""商品 / 文化资料库读取层。

支持两种后端（首期二选一即可）：
  - json   : 直接读 app/data/products.seed.json，零依赖，适合演示
  - sqlite : 读 app/data/teahouse.db，用 scripts/seed_sqlite.py 生成

可靠性设计：
  - 内存缓存 + 文件 mtime 判断，避免每次请求都读盘
  - 保留"上一次成功加载的快照"，读盘失败时降级使用并置 degraded 标记，
    保证演示现场不会因为磁盘/路径问题整个挂掉
  - 单条商品数据非法时只跳过该条并告警，不影响其余商品
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import CatalogUnavailableError
from app.models.enums import ReviewStatus
from app.models.product import Product

logger = logging.getLogger("qinba.catalog")


@dataclass
class CatalogSnapshot:
    """一次加载的结果。"""

    products: list[Product] = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str | None = None
    origin: str = "json"

    @property
    def approved(self) -> list[Product]:
        return [p for p in self.products if p.is_approved]

    @property
    def pending(self) -> list[Product]:
        return [p for p in self.products if p.review_status == ReviewStatus.PENDING_REVIEW]

    def find(self, product_id: str) -> Product | None:
        for product in self.products:
            if product.id == product_id:
                return product
        return None


class CatalogSource(Protocol):
    """后端存储需要实现的接口。"""

    def read(self) -> list[dict]:  # pragma: no cover - 协议声明
        ...


class JsonCatalogSource:
    def __init__(self, path: Path) -> None:
        self.path = path

    def fingerprint(self) -> float:
        return self.path.stat().st_mtime

    def read(self) -> list[dict]:
        with self.path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        if isinstance(payload, dict):
            items = payload.get("products", [])
        elif isinstance(payload, list):
            items = payload
        else:
            raise ValueError("商品资料文件结构无法识别，应为 {products: [...]} 或 [...]")
        if not isinstance(items, list):
            raise ValueError("products 字段必须是数组")
        return items


class SqliteCatalogSource:
    """SQLite 后端：单表存 JSON 文档，便于后续换成后台录入界面。"""

    TABLE = "products"

    def __init__(self, path: Path) -> None:
        self.path = path

    def fingerprint(self) -> float:
        return self.path.stat().st_mtime

    def read(self) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    f"SELECT payload FROM {self.TABLE} ORDER BY id"  # noqa: S608 - 表名固定
                ).fetchall()
            except sqlite3.OperationalError as exc:
                raise ValueError(
                    f"SQLite 资料库结构不正确（{exc}）。请先执行 python scripts/seed_sqlite.py"
                ) from exc
        return [json.loads(row["payload"]) for row in rows]

    @classmethod
    def initialize(cls, path: Path, products: list[dict]) -> int:
        """由种子 JSON 生成 SQLite 库。返回写入条数。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {cls.TABLE} (
                    id TEXT PRIMARY KEY,
                    review_status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(f"DELETE FROM {cls.TABLE}")
            conn.executemany(
                f"INSERT INTO {cls.TABLE} (id, review_status, payload) VALUES (?, ?, ?)",
                [
                    (
                        item.get("id", ""),
                        item.get("review_status", "pending_review"),
                        json.dumps(item, ensure_ascii=False),
                    )
                    for item in products
                ],
            )
            conn.commit()
        return len(products)


class CatalogRepository:
    """带缓存与降级能力的资料库门面。线程安全。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._cache: CatalogSnapshot | None = None
        self._cache_fingerprint: float | None = None
        self._last_good: CatalogSnapshot | None = None
        self._source: CatalogSource = self._build_source()

    # ---------- 内部 ----------
    def _build_source(self) -> CatalogSource:
        if self.settings.catalog_backend == "sqlite":
            return SqliteCatalogSource(self.settings.catalog_path)
        return JsonCatalogSource(self.settings.catalog_path)

    def _parse(self, raw_items: list[dict], origin: str) -> CatalogSnapshot:
        products: list[Product] = []
        invalid = 0
        for item in raw_items:
            try:
                products.append(Product.model_validate(item))
            except ValidationError as exc:
                invalid += 1
                identifier = item.get("id", "<无 id>") if isinstance(item, dict) else "<非对象>"
                logger.warning("跳过非法商品数据 id=%s：%s", identifier, exc.errors()[:2])
        if invalid:
            logger.warning("本次加载共跳过 %d 条非法商品数据", invalid)
        if not products and raw_items:
            raise CatalogUnavailableError("商品资料库内容全部无法解析，请检查数据格式")
        return CatalogSnapshot(products=products, origin=origin)

    # ---------- 对外 ----------
    @property
    def backend(self) -> str:
        return self.settings.catalog_backend

    @property
    def path(self) -> Path:
        return self.settings.catalog_path

    def load(self, force: bool = False) -> CatalogSnapshot:
        """读取资料库，必要时使用上次成功快照兜底。"""
        with self._lock:
            try:
                fingerprint = self._source.fingerprint()
            except FileNotFoundError:
                return self._fallback(f"资料库文件不存在：{self.path}")
            except OSError as exc:
                return self._fallback(f"资料库文件不可读：{exc}")

            if (
                not force
                and self._cache is not None
                and self._cache_fingerprint == fingerprint
            ):
                return self._cache

            try:
                raw_items = self._source.read()
                snapshot = self._parse(raw_items, origin=self.backend)
            except Exception as exc:  # noqa: BLE001 - 统一降级处理
                logger.warning("读取资料库失败（%s），尝试使用上次成功快照", exc)
                return self._fallback(str(exc))

            self._cache = snapshot
            self._cache_fingerprint = fingerprint
            self._last_good = snapshot
            logger.info(
                "资料库已加载 backend=%s 商品=%d 已审核=%d",
                snapshot.origin,
                len(snapshot.products),
                len(snapshot.approved),
            )
            return snapshot

    def _fallback(self, reason: str) -> CatalogSnapshot:
        if self._last_good is not None:
            logger.error("资料库读取失败，已降级使用上次成功快照：%s", reason)
            return CatalogSnapshot(
                products=self._last_good.products,
                degraded=True,
                degraded_reason=f"资料库读取失败，已使用最近一次成功加载的内容（{reason}）",
                origin=self._last_good.origin,
            )
        # 缓存也没命中，但种子 JSON 可能仍在（例如 SQLite 未生成）
        if self.settings.catalog_backend == "sqlite":
            seed = self.settings.resolve_path(self.settings.catalog_json_path)
            if seed.exists():
                logger.error("SQLite 不可用（%s），回退到种子 JSON：%s", reason, seed)
                snapshot = self._parse(
                    JsonCatalogSource(seed).read(), origin="json-fallback"
                )
                snapshot.degraded = True
                snapshot.degraded_reason = f"SQLite 资料库不可用，已回退到种子 JSON（{reason}）"
                self._source = JsonCatalogSource(seed)
                self._cache = snapshot
                self._last_good = snapshot
                return snapshot
        raise CatalogUnavailableError(f"无法读取商品资料库：{reason}")

    def approved_products(self) -> list[Product]:
        return self.load().approved

    def get_approved(self, product_id: str) -> Product | None:
        """只返回已审核商品：未过审一律按"不存在"处理。"""
        for product in self.load().approved:
            if product.id == product_id:
                return product
        return None

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
            self._cache_fingerprint = None

    def stats(self) -> dict:
        snapshot = self.load()
        return {
            "backend": snapshot.origin,
            "path": str(self.path),
            "total": len(snapshot.products),
            "approved": len(snapshot.approved),
            "pending": len(snapshot.pending),
            "degraded": snapshot.degraded,
            "degraded_reason": snapshot.degraded_reason,
        }
