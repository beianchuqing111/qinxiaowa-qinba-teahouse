"""茶舍编排层。

把"资料库 → 需求识别 → 受约束推荐 → 对白 → 外链校验"串成一次完整的接口调用，
对应架构图里的 "API / 编排层"。所有对外响应都在这里组装，保证字段来源单一。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.core.config import Settings
from app.core.errors import ProductNotFoundError
from app.core.security import ShopLinkGuard
from app.data.repository import CatalogRepository
from app.models.api_schemas import (
    RecommendMeta,
    RecommendRequest,
    RecommendResponse,
    RecommendationOut,
)
from app.models.enums import DialogueSource, PurchaseMode, RecommendResult
from app.models.product import Product
from app.services.dialogue import DialogueService
from app.services.intent import IntentService
from app.services.recommender import Recommender
from app.services.session import SessionStore

logger = logging.getLogger("qinba.teahouse")


class TeahouseService:
    def __init__(
        self,
        settings: Settings,
        catalog: CatalogRepository,
        intent_service: IntentService,
        recommender: Recommender,
        dialogue: DialogueService,
        sessions: SessionStore,
        link_guard: ShopLinkGuard,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.intent_service = intent_service
        self.recommender = recommender
        self.dialogue = dialogue
        self.sessions = sessions
        self.link_guard = link_guard

    # ---------- 外链 ----------
    def _resolve_shop_link(self, product: Product) -> tuple[dict[str, Any] | None, str, str | None]:
        """返回 (可对外的 shop_link, purchase_mode, 被拒原因)。"""
        if not product.shop_link.enabled:
            return None, PurchaseMode.DISPLAY_ONLY.value, None
        decision = self.link_guard.evaluate(product.shop_link.url, platform=product.shop_link.platform)
        if not decision.allowed:
            return (
                None,
                PurchaseMode.DISPLAY_ONLY.value,
                self.link_guard.describe_disabled_reason(decision.reason),
            )
        return (
            {
                "platform": product.shop_link.platform,
                "url": decision.url,
                "host": decision.host,
                "label": product.shop_link.label or f"前往{product.shop_link.platform}查看同款",
                "disclosure": f"将跳转到{product.shop_link.platform}的真实商品页，请以店铺页面信息为准",
            },
            PurchaseMode.EXTERNAL_LINK.value,
            None,
        )

    # ---------- 商品序列化 ----------
    def serialize_price(self, product: Product) -> dict[str, Any]:
        price = product.price
        payload: dict[str, Any] = {
            "amount_cents": price.amount_cents,
            "currency": price.currency,
            "unit": price.unit,
            "verified": price.verified,
            "display": price.display if price.verified else None,
        }
        if not price.verified:
            payload["display"] = "价格待核验"
            payload["note"] = "该商品价格资料尚未核验，页面不展示具体金额"
        elif price.note:
            payload["note"] = price.note
        return payload

    def serialize_specs(self, product: Product) -> list[dict[str, Any]]:
        return [
            {"label": item.label, "value": item.value}
            for item in product.specs
            if item.verified
        ]

    def serialize_culture_card(self, product: Product) -> dict[str, Any]:
        card = product.culture_card
        return {
            "title": card.title,
            "origin": card.origin if card.origin_verified else None,
            "origin_verified": card.origin_verified,
            "origin_note": None if card.origin_verified else "该商品的产地明细资料尚未提供，不做展示",
            "paragraphs": list(card.paragraphs),
            "facts": list(card.facts),
            "verification_note": card.verification_note,
            "sources": list(card.sources),
        }

    def serialize_source_status(self, product: Product) -> dict[str, Any]:
        source = product.source
        return {
            "review_status": product.review_status.value,
            "review_status_label": "已审核" if product.is_approved else "待审核",
            "material_source": source.material_source,
            "reviewer": source.reviewer,
            "reviewed_at": source.reviewed_at,
            "notes": source.notes,
        }

    def serialize_product(self, product: Product) -> dict[str, Any]:
        shop_link, purchase_mode, link_reason = self._resolve_shop_link(product)
        payload = {
            "product_id": product.id,
            "name": product.name,
            "subtitle": product.subtitle,
            "category": product.category,
            "image_url": product.images[0] if product.images else None,
            "image_urls": list(product.images),
            "price": self.serialize_price(product),
            "specs": self.serialize_specs(product),
            "culture_card": self.serialize_culture_card(product),
            "source_status": self.serialize_source_status(product),
            "shop_link": shop_link,
            "purchase_mode": purchase_mode,
            "missing_facts": list(product.missing_facts),
            "tags": product.tags.model_dump(),
        }
        if link_reason:
            payload["shop_link_disabled_reason"] = link_reason
        return payload

    # ---------- 推荐主流程 ----------
    async def recommend(self, request: RecommendRequest, *, is_switch: bool = False) -> RecommendResponse:
        started = time.perf_counter()
        trace_id = uuid.uuid4().hex[:12]

        snapshot = self.catalog.load()
        pool = snapshot.approved

        extraction = self.intent_service.normalize(request)
        intent = extraction.intent

        # 排除项：显式传入的商品 ID 一定排除；
        # 「换一款」时再叠加会话里已经看过的全部商品，避免来回重复同一款。
        session_state = self.sessions.get(request.session_id)
        exclude_ids: list[str] = []
        if request.excluded_product_id:
            exclude_ids.append(request.excluded_product_id)
        if is_switch and session_state is not None:
            if session_state.current_product_id:
                exclude_ids.append(session_state.current_product_id)
            exclude_ids.extend(session_state.seen_product_ids)

        outcome = self.recommender.recommend(intent, pool=pool, exclude_ids=exclude_ids)

        meta = RecommendMeta(
            trace_id=trace_id,
            catalog_backend=snapshot.origin,
            candidate_count=outcome.candidate_count,
            eligible_count=outcome.eligible_count,
            relaxed=outcome.relaxed,
            relaxed_reason=outcome.relaxed_reason,
            degraded=snapshot.degraded,
            degraded_reason=snapshot.degraded_reason,
        )

        if outcome.result != RecommendResult.OK or outcome.product is None:
            if not pool:
                message = "商品资料还在核验中，茶舍暂时没有可以推荐的茶品，欢迎稍后再来。"
            elif is_switch:
                message = "暂无其他匹配"
            else:
                message = self.recommender.no_match_message(intent)
            meta.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return RecommendResponse(
                result=outcome.result,
                message=message,
                intent=intent,
                recommendation=None,
                alternatives_available=False,
                meta=meta,
            )

        product = outcome.product
        # 先做外链校验，确保对白与推荐理由里的"购买出口"与实际下发结果一致
        shop_link, purchase_mode, link_reason = self._resolve_shop_link(product)

        dialogue_result = await self.dialogue.compose(
            product,
            intent,
            is_switch=is_switch,
            relaxed_reason=outcome.relaxed_reason,
            purchase_mode=purchase_mode,
        )
        meta.dialogue_source = dialogue_result.source
        if dialogue_result.degraded:
            meta.degraded = True
            meta.degraded_reason = dialogue_result.degraded_reason

        recommendation = RecommendationOut(
            product_id=product.id,
            name=product.name,
            subtitle=product.subtitle,
            image_url=product.images[0] if product.images else None,
            image_urls=list(product.images),
            price=self.serialize_price(product),
            specs=self.serialize_specs(product),
            dialogue=dialogue_result.dialogue,
            reason=dialogue_result.reason,
            reason_points=dialogue_result.reason_points,
            culture_card=self.serialize_culture_card(product),
            source_status=self.serialize_source_status(product),
            shop_link=shop_link,
            purchase_mode=purchase_mode,
            shop_link_note=link_reason,
            missing_facts=list(product.missing_facts),
            match_score=outcome.score,
        )

        # 外链未接入属于"预期状态"，不是故障：只记备注，不标 degraded
        if link_reason:
            meta.notes.append(link_reason)
        if outcome.relaxed_reason:
            meta.notes.append(outcome.relaxed_reason)

        meta.elapsed_ms = int((time.perf_counter() - started) * 1000)

        # 记录会话，供"换一款"自动排除
        self.sessions.touch(
            request.session_id,
            current_product_id=product.id,
            last_request=request.model_dump(mode="json"),
        )

        return RecommendResponse(
            result=RecommendResult.OK,
            message=outcome.message,
            intent=intent,
            recommendation=recommendation,
            alternatives_available=outcome.alternatives_available,
            meta=meta,
        )

    # ---------- 资料展示 ----------
    def get_product(self, product_id: str) -> dict[str, Any]:
        product = self.catalog.get_approved(product_id)
        if product is None:
            raise ProductNotFoundError()
        payload = self.serialize_product(product)
        safe = {
            "product_id": payload["product_id"],
            "name": payload["name"],
            "subtitle": payload["subtitle"],
            "category": payload["category"],
            "image_url": payload["image_url"],
            "image_urls": payload["image_urls"],
            "price": payload["price"],
            "specs": payload["specs"],
            "culture_card": payload["culture_card"],
        }
        return {
            "product": safe,
            "source_status": payload["source_status"],
            "shop_link": payload["shop_link"],
            "purchase_mode": payload["purchase_mode"],
            "missing_facts": payload["missing_facts"],
        }

    def outbound_link(self, product_id: str) -> dict[str, Any]:
        """查看 / 离站：只有白名单内的真实链接才会返回。"""
        product = self.catalog.get_approved(product_id)
        if product is None:
            raise ProductNotFoundError()

        shop_link, purchase_mode, reason = self._resolve_shop_link(product)
        if shop_link is None:
            return {
                "product_id": product.id,
                "allowed": False,
                "purchase_mode": purchase_mode,
                "url": None,
                "label": None,
                "host": None,
                "message": reason or "该商品暂未接入线上店铺，这里只展示已核验的资料",
            }
        return {
            "product_id": product.id,
            "allowed": True,
            "purchase_mode": purchase_mode,
            "url": shop_link["url"],
            "label": shop_link["label"],
            "host": shop_link["host"],
            "message": shop_link["disclosure"],
        }

    # ---------- 选项与演示用例 ----------
    def options(self) -> dict[str, Any]:
        from app.models.enums import (
            PREFERENCE_LABELS,
            RECIPIENT_LABELS,
            SCENE_LABELS,
            Preference,
            Recipient,
            Scene,
        )

        scene_desc = {
            Scene.SELF.value: "想给自己找一款日常喝的茶",
            Scene.GIFT.value: "要带一份送人，需要体面又稳妥",
            Scene.ANKANG_INTRO.value: "想从一杯茶开始了解安康",
        }
        preference_desc = {
            Preference.GREEN_TEA.value: "偏清爽的绿茶",
            Preference.BLACK_TEA.value: "偏醇厚的红茶",
            Preference.DARK_TEA.value: "耐泡耐存的黑茶、茯茶",
            Preference.LIGHT.value: "口味清淡不刺激",
            Preference.RICH.value: "口感厚一点、回甘明显",
            Preference.GIFT_READY.value: "需要有礼盒和手提袋",
            Preference.PORTABLE.value: "办公室或随身冲泡",
            Preference.HEALTHY.value: "偏好无添加、日常养生",
            Preference.BEGINNER.value: "喝茶不多，想要容易入口的",
        }

        return {
            "scenes": [
                {"value": item.value, "label": SCENE_LABELS[item.value], "description": scene_desc.get(item.value, "")}
                for item in Scene
            ],
            "recipients": [
                {"value": item.value, "label": RECIPIENT_LABELS[item.value], "description": ""}
                for item in Recipient
            ],
            "preferences": [
                {"value": item.value, "label": PREFERENCE_LABELS[item.value], "description": preference_desc.get(item.value, "")}
                for item in Preference
            ],
            "budget_hints": [
                {"label": "不限预算", "budget": None},
                {"label": "100 元以内", "budget": 100},
                {"label": "100-300 元", "budget": {"min": 100, "max": 300}},
                {"label": "300 元以上", "budget": 300},
            ],
            "demo_cases": self.demo_cases(),
        }

    @staticmethod
    def demo_cases() -> list[dict[str, Any]]:
        """3 个可重复演示的案例，与分工方案第 05 节的验收路径一致。"""
        return [
            {
                "id": "case-self",
                "title": "案例一 · 自用",
                "description": "扫码入店 → 选自用 → 推荐一款 → 看文化卡",
                "request": {
                    "scene": "self",
                    "budget": 150,
                    "preference": ["light", "beginner"],
                    "session_id": "demo-self",
                },
            },
            {
                "id": "case-gift",
                "title": "案例二 · 礼赠长辈",
                "description": "选自用/礼赠 → 送给长辈 → 要礼盒 → 换一款 → 查看店铺",
                "request": {
                    "scene": "gift",
                    "recipient": "elder",
                    "budget": {"min": 100, "max": 300},
                    "preference": ["gift_ready"],
                    "session_id": "demo-gift",
                },
            },
            {
                "id": "case-ankang",
                "title": "案例三 · 了解安康",
                "description": "选了不了解安康 → 文化与产地为主 → 无依据处明确说明",
                "request": {
                    "scene": "ankang_intro",
                    "preference": "想了解一下安康本地的茶",
                    "session_id": "demo-ankang",
                },
                "follow_up": {"switch": True},
            },
        ]
