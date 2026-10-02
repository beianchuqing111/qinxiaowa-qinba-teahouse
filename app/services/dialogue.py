"""对白与推荐理由生成。

策略：模板优先，大模型只做"锦上添花"的措辞改写。
  - 模板对白完全由已核验字段拼装，天然不会编造事实，是演示现场的稳定兜底
  - 若配置了大模型，则把「允许事实 + 模板草稿」交给模型润色，
    再用 FactGuard 校验；任一条不通过就丢弃模型输出并回退模板
这样即使模型不可用、超时、或试图编造，访客看到的依然是合规对白。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import Settings
from app.models.api_schemas import NormalizedIntent
from app.models.enums import (
    PREFERENCE_LABELS,
    DialogueSource,
    PurchaseMode,
    Recipient,
)
from app.models.product import Product
from app.services.fact_guard import FactGuard
from app.services.llm import LlmClient

logger = logging.getLogger("qinba.dialogue")

# 场景/对象的招呼语，用数据字段拼，不含任何事实性断言
OPENERS: dict[str, str] = {
    "self": "自己喝的话，我一般先看顺不顺口。",
    "gift": "送人的东西，我尽量挑得稳妥些。",
    "ankang_intro": "想认识安康，从一杯本地的茶开始最直接。",
}

RECIPIENT_OPENERS: dict[str, str] = {
    Recipient.ELDER.value: "给长辈带茶，稳妥比新奇重要。",
    Recipient.PARENT.value: "给家里人带一份，图的是他们喝着舒服。",
    Recipient.FRIEND.value: "送朋友不用太讲究，好喝最要紧。",
    Recipient.CLIENT.value: "给客户的这份，包装和体面都得顾上。",
    Recipient.PARTNER.value: "给身边人带一份，心意到了就好。",
    Recipient.KID.value: "给孩子的口味，我挑得更轻一些。",
    Recipient.SELF.value: "自己喝，就挑个省心的。",
}

TASTING_HINTS: dict[str, str] = {
    "绿茶": "滋味偏清淡、回甘，适合日常慢慢泡。",
    "红茶": "滋味偏醇厚，冷天喝或者配点心都合适。",
    "黑茶": "耐泡耐存，越放越顺口。",
    "白茶": "口味清甜，接受度高。",
    "代用茶": "口味清淡，日常当水喝也行。",
}


@dataclass
class DialogueResult:
    dialogue: str
    reason: str
    reason_points: list[str] = field(default_factory=list)
    source: DialogueSource = DialogueSource.TEMPLATE
    degraded: bool = False
    degraded_reason: str | None = None


class DialogueService:
    def __init__(self, settings: Settings, llm: LlmClient) -> None:
        self.settings = settings
        self.llm = llm

    # ---------- 模板 ----------
    def greeting(self, intent: NormalizedIntent | None = None) -> str:
        """迎宾态对白，不涉及任何商品事实。"""
        if intent and intent.scene_label:
            base = OPENERS.get(intent.scene.value, "欢迎进茶舍坐坐。")
            if intent.recipient_label and intent.recipient_label not in ("自己",):
                return f"{base}这次是给{intent.recipient_label}挑，还是您自己喝？"
            return base
        return "欢迎来秦巴茶舍坐坐。想自己喝，还是带一份送人？我按您的需求挑一款。"

    def _fact_sentence(self, product: Product) -> str:
        """只用已核验字段的事实句。"""
        parts: list[str] = []
        specs = product.verified_spec_lines()
        if specs:
            parts.append(specs[0])
            if len(specs) > 1:
                parts.append(specs[1])
        if product.culture_card.origin and product.culture_card.origin_verified:
            parts.append(f"产地是{product.culture_card.origin}")
        if parts:
            return f"{product.name}，{'，'.join(parts)}。"
        return f"{product.name}。"

    def _tasting_sentence(self, product: Product) -> str:
        hint = TASTING_HINTS.get(product.category)
        if hint:
            return hint
        facts = product.culture_card.facts
        if facts:
            return f"{facts[-1].rstrip('。')}。"
        return "具体口感我这边没有更多依据，就不替您下结论了。"

    def _missing_sentence(self, product: Product) -> str | None:
        """把"资料缺失"明确说出来，而不是含糊带过。"""
        if not product.missing_facts:
            return None
        first = product.missing_facts[0].rstrip("。")
        return f"有一点先说明：{first}。"

    def build_template(
        self,
        product: Product,
        intent: NormalizedIntent,
        *,
        is_switch: bool = False,
        relaxed_reason: str | None = None,
        purchase_mode: str | None = None,
    ) -> DialogueResult:
        sentences: list[str] = []

        if is_switch:
            sentences.append("那换一款给您看看。")
        elif intent.recipient and intent.recipient != Recipient.SELF:
            opener = RECIPIENT_OPENERS.get(intent.recipient.value)
            sentences.append(opener or OPENERS.get(intent.scene.value, "我挑了一款。"))
        else:
            sentences.append(OPENERS.get(intent.scene.value, "我挑了一款。"))

        sentences.append(self._fact_sentence(product))

        if product.price.verified:
            sentences.append(f"价格是{product.price.display}。")
        else:
            sentences.append("价格这边还没有核验，我暂时不报数，页面上也不会显示。")

        sentences.append(self._tasting_sentence(product))

        missing = self._missing_sentence(product)
        if missing:
            sentences.append(missing)
        if relaxed_reason:
            sentences.append(relaxed_reason)

        dialogue = "".join(sentences)

        reason_points = self._reason_points(product, intent, purchase_mode)
        reason = self._reason_text(product, intent, is_switch=is_switch, purchase_mode=purchase_mode)
        return DialogueResult(dialogue=dialogue, reason=reason, reason_points=reason_points)

    def _effective_mode(self, product: Product, purchase_mode: str | None) -> PurchaseMode:
        """购买出口以"外链校验后的实际结果"为准，而不是商品资料的原始标记。"""
        if purchase_mode:
            return PurchaseMode(purchase_mode)
        return product.purchase_mode

    def _reason_points(
        self, product: Product, intent: NormalizedIntent, purchase_mode: str | None = None
    ) -> list[str]:
        points: list[str] = []
        if intent.scene_label:
            points.append(f"需求场景：{intent.scene_label}")
        if intent.recipient_label:
            points.append(f"适用对象：{intent.recipient_label}")
        if product.price.verified:
            points.append(f"价格：{product.price.display}")
        specs = product.verified_spec_lines()
        if specs:
            points.append("规格：" + "；".join(specs))
        if product.culture_card.origin and product.culture_card.origin_verified:
            points.append(f"产地：{product.culture_card.origin}")
        matched = [
            PREFERENCE_LABELS.get(item, item)
            for item in product.tags.preferences
            if item in intent.preferences
        ]
        if matched:
            points.append("命中偏好：" + "、".join(matched))
        if self._effective_mode(product, purchase_mode) == PurchaseMode.EXTERNAL_LINK:
            points.append(f"购买出口：已接入{product.shop_link.platform}，页面会明示跳转")
        else:
            points.append("购买出口：未接入线上店铺，仅展示已核验资料")
        for item in product.missing_facts:
            points.append(f"资料缺失：{item}")
        return points

    def _reason_text(
        self,
        product: Product,
        intent: NormalizedIntent,
        *,
        is_switch: bool,
        purchase_mode: str | None = None,
    ) -> str:
        target = intent.recipient_label or "您"
        head = f"按「{intent.scene_label}」为{target}筛选"
        if intent.budget_display:
            head += f"，预算 {intent.budget_display}"
        if intent.preference_labels:
            head += "，" + "、".join(intent.preference_labels)
        head += "，在已录入并审核通过的商品里匹配到这款。"

        if self._effective_mode(product, purchase_mode) == PurchaseMode.EXTERNAL_LINK:
            tail = f"已接入{product.shop_link.platform}，可点击按钮跳转到真实商品页核对。"
        else:
            tail = "暂未接入线上店铺，页面只展示已核验资料，不提供下单入口。"
        if is_switch:
            tail = "已按您的要求避开上一款。" + tail
        return head + tail

    # ---------- 大模型润色 ----------
    async def compose(
        self,
        product: Product,
        intent: NormalizedIntent,
        *,
        is_switch: bool = False,
        relaxed_reason: str | None = None,
        purchase_mode: str | None = None,
    ) -> DialogueResult:
        template = self.build_template(
            product,
            intent,
            is_switch=is_switch,
            relaxed_reason=relaxed_reason,
            purchase_mode=purchase_mode,
        )

        if not self.settings.llm_ready:
            return template

        guard = FactGuard(product)
        prompt = self._build_prompt(product, intent, template.dialogue, guard, is_switch=is_switch)
        llm_result = await self.llm.rewrite_dialogue(prompt)

        if llm_result is None:
            template.degraded = True
            template.degraded_reason = "大模型不可用或超时，已使用内置对白"
            return template

        verdict = guard.validate(llm_result.text)
        if not verdict.ok:
            logger.warning("大模型对白未通过事实护栏，已回退模板：%s", verdict.reason())
            template.source = DialogueSource.LLM_REJECTED
            template.degraded = True
            template.degraded_reason = f"大模型输出未通过事实护栏，已回退模板（{verdict.reason()}）"
            return template

        template.dialogue = llm_result.text
        template.source = DialogueSource.LLM
        return template

    def _build_prompt(
        self,
        product: Product,
        intent: NormalizedIntent,
        draft: str,
        guard: FactGuard,
        *,
        is_switch: bool,
    ) -> str:
        scene_line = f"场景：{intent.scene_label}"
        if intent.recipient_label:
            scene_line += f"；送礼对象：{intent.recipient_label}"
        if intent.budget_display:
            scene_line += f"；预算：{intent.budget_display}"
        if intent.preference_labels:
            scene_line += "；偏好：" + "、".join(intent.preference_labels)
        if is_switch:
            scene_line += "；本次是「换一款」，开场要体现换了另一款"

        return (
            "【允许事实】（只能使用以下内容，不得新增）\n"
            f"{guard.allowed_fact_brief()}\n\n"
            f"【访客需求】\n{scene_line}\n\n"
            f"【模板草稿】（意思不要变，可以换更自然的说法）\n{draft}\n\n"
            "请输出改写后的对白，两到三句、60-110 字，不要数字，不要 emoji。"
        )
