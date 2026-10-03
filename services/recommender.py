"""受约束推荐。

对应分工方案："识别送礼对象、预算和偏好；仅在已录入、已审核商品内筛选"、
"返回单款推荐及理由；换一款避开当前商品"。

三条铁律：
  1. 候选池只能是 review_status=approved 的商品，未过审的一律看不到
  2. 打分只用资料库里存在的字段，缺字段就当不匹配，不做任何猜测补全
  3. 严格条件下无解时，宁可明确返回"暂无其他匹配"，也不硬凑；
     只有在放宽约束能改善体验时才放宽，并且必须把放宽原因说清楚
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.core.config import Settings
from app.models.api_schemas import NormalizedIntent
from app.models.enums import RecommendResult
from app.models.product import Product

logger = logging.getLogger("qinba.recommender")

# 打分权重（纯业务可调参数，集中在此便于评审）
W_SCENE = 40
W_RECIPIENT = 25
W_BUDGET_IN = 25
W_PREFERENCE_EACH = 8
W_PREFERENCE_CAP = 24
W_PRICE_VERIFIED = 3
# 刻意不给"有外链"加分：是否存在店铺链接与访客需求无关，
# 打分偏向有链接的商品会变相制造导流，违背"不制造虚假购买入口"的前提。


@dataclass
class ScoredProduct:
    product: Product
    score: int
    hits: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    result: RecommendResult
    product: Product | None = None
    score: int = 0
    hits: list[str] = field(default_factory=list)
    message: str = ""
    relaxed: bool = False
    relaxed_reason: str | None = None
    candidate_count: int = 0
    eligible_count: int = 0
    alternatives_available: bool = False


class Recommender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---------- 打分 ----------
    def _score(self, product: Product, intent: NormalizedIntent) -> ScoredProduct:
        score = 0
        hits: list[str] = []

        if intent.scene.value in product.tags.scenes:
            score += W_SCENE
            hits.append(f"场景命中「{intent.scene_label}」")

        if intent.recipient and intent.recipient.value in product.tags.recipients:
            score += W_RECIPIENT
            hits.append(f"适用对象命中「{intent.recipient_label}」")

        budget_max = intent.budget_max_yuan
        budget_min = intent.budget_min_yuan
        price_yuan = product.price.amount_yuan if product.price.verified else None

        if budget_max is None and budget_min is None:
            score += W_BUDGET_IN
            hits.append("未设置预算，不限制")
        elif price_yuan is None:
            hits.append("该商品价格尚未核验，暂不参与预算比对")
        else:
            above = budget_max is not None and price_yuan > budget_max
            below = budget_min is not None and price_yuan < budget_min
            if not above and not below:
                score += W_BUDGET_IN
                hits.append(f"价格 {product.price.display} 落在预算内")
            elif below:
                score += W_BUDGET_IN - 6
                hits.append(f"价格 {product.price.display} 低于预算下沿")
            else:
                over = price_yuan - float(budget_max)
                penalty = min(20, 6 + int(over / 50) * 3)
                score += W_BUDGET_IN - penalty
                hits.append(f"价格 {product.price.display} 略高于预算")

        overlap = [item for item in product.tags.preferences if item in intent.preferences]
        if overlap:
            gained = min(W_PREFERENCE_CAP, W_PREFERENCE_EACH * len(overlap))
            score += gained
            hits.append(f"偏好命中 {len(overlap)} 项")

        if product.price.verified:
            score += W_PRICE_VERIFIED

        return ScoredProduct(product=product, score=score, hits=hits)

    # ---------- 主流程 ----------
    def recommend(
        self,
        intent: NormalizedIntent,
        *,
        pool: list[Product],
        exclude_ids: Iterable[str] | None = None,
    ) -> Outcome:
        candidate_count = len(pool)

        excluded: set[str] = {item for item in (exclude_ids or []) if item}
        if intent.excluded_product_id:
            excluded.add(intent.excluded_product_id)

        eligible = [item for item in pool if item.id not in excluded]
        eligible_count = len(eligible)

        if not eligible:
            message = (
                f"目前只有 {candidate_count} 款已审核商品，已经全部看过了，暂无其他匹配。"
                if candidate_count
                else "商品资料还在核验中，暂时没有可以推荐的茶品。"
            )
            return Outcome(
                result=RecommendResult.NO_OTHER_MATCH if candidate_count else RecommendResult.NO_MATCH,
                message=message,
                candidate_count=candidate_count,
                eligible_count=eligible_count,
            )

        budget_max = intent.budget_max_yuan
        budget_min = intent.budget_min_yuan
        scene = intent.scene.value

        # ---- 第一层：场景 + 预算 严格命中 ----
        strict: list[Product] = []
        for item in eligible:
            if scene not in item.tags.scenes:
                continue
            if budget_max is not None and item.price.verified and item.price.amount_yuan > budget_max:
                continue
            strict.append(item)

        relaxed_reason: str | None = None
        working = strict

        # ---- 第二层：放宽预算（保留场景），挑"最接近预算"的一款 ----
        if not working and budget_max is not None:
            same_scene = [item for item in eligible if scene in item.tags.scenes]
            if same_scene:
                working = sorted(
                    same_scene,
                    key=lambda item: (
                        max(0.0, item.price.amount_yuan - budget_max),
                        item.id,
                    ),
                )[:1]
                relaxed_reason = f"预算 {intent.budget_display} 内暂时没有完全匹配的，为您找到最接近的一款。"

        # ---- 第三层：放宽场景（例如资料里还没给该场景打标签）----
        if not working:
            working = eligible
            relaxed_reason = (
                relaxed_reason
                or f"「{intent.scene_label}」场景下的商品资料还在整理，先为您推荐已审核的茶品。"
            )
            logger.warning(
                "场景 %s 无匹配商品，已放宽到全部已审核商品（共 %d 款）",
                scene,
                len(eligible),
            )

        scored = [self._score(item, intent) for item in working]
        scored.sort(key=lambda item: (-item.score, item.product.id))
        best = scored[0]

        others = [item for item in eligible if item.id != best.product.id]
        result = RecommendResult.OK
        message = f"为您推荐「{best.product.name}」"

        if relaxed_reason:
            message = f"{message}（{relaxed_reason}）"

        return Outcome(
            result=result,
            product=best.product,
            score=best.score,
            hits=best.hits,
            message=message,
            relaxed=relaxed_reason is not None,
            relaxed_reason=relaxed_reason,
            candidate_count=candidate_count,
            eligible_count=eligible_count,
            alternatives_available=bool(others),
        )

    # ---------- 兜底提示 ----------
    def no_match_message(self, intent: NormalizedIntent) -> str:
        hints: list[str] = []
        if intent.budget_max_yuan is not None:
            hints.append("把预算放宽一些")
        if intent.preferences:
            hints.append("减少几个口味偏好")
        if not hints:
            hints.append("换一种需求再试")
        return "按当前需求暂时没有匹配的茶品，可以" + "，或者".join(hints) + "。"
