"""需求识别与字段归一化。

对应分工方案："校验场景、预算、偏好等输入"、"识别送礼对象、预算和偏好"。

这一层只做"把访客的话翻译成结构化约束"，不做任何事实生成。
无法识别的词会原样放进 unknown_preferences 回传，前端可以显示
"没听懂这部分，已按其余条件推荐"，而不是让后端瞎猜。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings
from app.models.api_schemas import BudgetIn, NormalizedIntent, RecommendRequest
from app.models.enums import (
    PREFERENCE_LABELS,
    RECIPIENT_LABELS,
    SCENE_LABELS,
    Preference,
    Recipient,
)

# ---------- 关键词表：中文口语 -> 结构化标签 ----------
PREFERENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    Preference.GREEN_TEA.value: ("绿茶", "毛尖", "龙井", "碧螺春", "青茶味", "绿"),
    Preference.BLACK_TEA.value: ("红茶", "金骏眉", "正山小种", "红"),
    Preference.DARK_TEA.value: ("黑茶", "茯茶", "茯砖", "普洱", "砖茶"),
    Preference.WHITE_TEA.value: ("白茶", "银针", "寿眉"),
    Preference.LIGHT.value: ("清淡", "淡一点", "清爽", "不浓", "清口", "鲜爽"),
    Preference.RICH.value: ("醇厚", "浓郁", "浓一点", "厚重", "耐泡", "回甘强"),
    Preference.SWEET_AROMA.value: ("甜", "蜜香", "回甜", "香甜"),
    Preference.FLORAL.value: ("花香", "兰香", "花", "香高"),
    Preference.GIFT_READY.value: ("礼盒", "礼品", "包装", "送人", "伴手礼", "手提袋", "体面"),
    Preference.PORTABLE.value: ("便携", "小罐", "办公", "随身", "随手泡", "杯装", "冷泡"),
    Preference.HEALTHY.value: ("健康", "无添加", "无糖", "养生", "解腻", "清爽不腻", "天然"),
    Preference.BEGINNER.value: ("入门", "新手", "刚开始喝", "不太会", "没喝过", "容易接受", "不苦"),
}

RECIPIENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    Recipient.ELDER.value: ("长辈", "爷爷", "奶奶", "外公", "外婆", "老人"),
    Recipient.PARENT.value: ("父母", "爸", "妈", "妈妈", "爸爸", "家里"),
    Recipient.CLIENT.value: ("客户", "领导", "老板", "商务", "甲方", "合作伙伴", "老师"),
    Recipient.FRIEND.value: ("朋友", "同事", "同学", "闺蜜", "哥们"),
    Recipient.PARTNER.value: ("爱人", "老婆", "老公", "对象", "女朋友", "男朋友", "伴侣"),
    Recipient.KID.value: ("孩子", "小朋友", "儿子", "女儿", "晚辈"),
    Recipient.SELF.value: ("自己", "自用", "我自己"),
}

# 中文数字，用于解析 "一两百" "三百" 这类口语预算
CN_DIGITS = {
    "零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
BUDGET_RANGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|~|～|—|到|至|元到)\s*(\d+(?:\.\d+)?)")
BUDGET_NUMBER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
BUDGET_HINT_WORDS = ("元", "块", "钱", "预算", "左右", "上下", "以内", "以下", "不超过", "rmb", "¥")
BUDGET_ABOUT_WORDS = ("左右", "上下", "大概", "差不多", "约")


def _cn_number_to_int(text: str) -> int | None:
    """把 '三百' / '两百' / '一百五' 粗略转成整数。"""
    text = text.strip()
    total = 0
    if "百" in text:
        head, _, tail = text.partition("百")
        hundreds = CN_DIGITS.get(head, 1 if head == "" else None)
        if hundreds is None:
            return None
        total = hundreds * 100
        if tail:
            tens = CN_DIGITS.get(tail[0])
            if tens is not None:
                total += tens * 10
    elif "十" in text:
        head, _, tail = text.partition("十")
        tens = CN_DIGITS.get(head, 1 if head == "" else None)
        if tens is None:
            return None
        total = tens * 10 + CN_DIGITS.get(tail[0], 0) if tail else tens * 10
    else:
        return None
    return total or None


@dataclass
class IntentExtraction:
    intent: NormalizedIntent
    warnings: list[str]


class IntentService:
    """把请求体归一化成一个明确、可解释的需求对象。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---------- 预算 ----------
    def parse_budget(
        self, raw: BudgetIn | float | int | str | None
    ) -> tuple[float | None, float | None, str | None]:
        """返回 (min, max, display)。无法识别则返回 (None, None, None)。"""
        if raw is None:
            return None, None, None

        if isinstance(raw, BudgetIn):
            low, high = raw.min, raw.max
            return low, high, self._format_budget(low, high)

        if isinstance(raw, (int, float)):
            value = float(raw)
            return (None, value, self._format_budget(None, value)) if value > 0 else (None, None, None)

        text = str(raw).strip()
        if not text:
            return None, None, None

        # 1) 明确区间："100-300" / "一百到三百"
        match = BUDGET_RANGE_PATTERN.search(text)
        if match:
            low, high = float(match.group(1)), float(match.group(2))
            if low > high:
                low, high = high, low
            return low, high, self._format_budget(low, high)

        # 2) 阿拉伯数字（可能带"以内/左右"）
        numbers = BUDGET_NUMBER_PATTERN.findall(text)
        if numbers:
            value = float(numbers[-1])
            is_ceiling = any(word in text for word in ("以内", "以下", "不超过", "最多", "上限"))
            is_approx = any(word in text for word in BUDGET_ABOUT_WORDS)
            if is_ceiling:
                return None, value, self._format_budget(None, value)
            if is_approx:
                # "200 左右" 给出宽松上限，避免把刚好贵一点的商品直接排除
                return None, round(value * 1.2, 2), f"{self._format_number(value)} 元上下"
            if any(word in text.lower() for word in BUDGET_HINT_WORDS) or text.replace(".", "").isdigit():
                return None, value, self._format_budget(None, value)
            return None, value, self._format_budget(None, value)

        # 3) 中文数字："一两百" / "三百左右"
        for token in re.findall(r"[零一两二三四五六七八九十百]+", text):
            value = _cn_number_to_int(token)
            if value:
                if "一两" in text or "两三" in text:
                    return 100.0, 300.0, "100-300 元"
                return None, float(value), self._format_budget(None, float(value))

        return None, None, None

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{int(value)}" if float(value).is_integer() else f"{value:.2f}"

    def _format_budget(self, low: float | None, high: float | None) -> str | None:
        if low is not None and high is not None:
            return f"{self._format_number(low)}-{self._format_number(high)} 元"
        if high is not None:
            return f"{self._format_number(high)} 元以内"
        if low is not None:
            return f"{self._format_number(low)} 元以上"
        return None

    # ---------- 偏好 / 对象 ----------
    def _match_keywords(self, text: str, table: dict[str, tuple[str, ...]]) -> list[str]:
        hits: list[str] = []
        haystack = text.lower()
        for value, keywords in table.items():
            for keyword in keywords:
                if keyword.lower() in haystack:
                    if value not in hits:
                        hits.append(value)
                    break
        return hits

    def raw_tokens(self, raw: list[str] | str | None, free_text: str | None = None) -> list[str]:
        """把前端可能传的偏好（数组或一段中文）统一成字符串列表。"""
        tokens: list[str] = []
        if isinstance(raw, str):
            tokens = [raw]
        elif isinstance(raw, list):
            tokens = [str(item) for item in raw if str(item).strip()]
        if free_text:
            tokens.append(free_text)
        return tokens

    def normalize_preferences(
        self, raw: list[str] | str | None, free_text: str | None = None
    ) -> tuple[list[str], list[str], list[str]]:
        """返回 (已识别标签, 未识别原词, 原始输入词)。"""
        recognized: list[str] = []
        unknown: list[str] = []
        valid = {item.value for item in Preference}

        tokens = self.raw_tokens(raw, free_text)

        for token in tokens:
            cleaned = token.strip()[: self.settings.max_preference_chars]
            if not cleaned:
                continue
            if cleaned in valid:
                if cleaned not in recognized:
                    recognized.append(cleaned)
                continue
            hits = self._match_keywords(cleaned, PREFERENCE_KEYWORDS)
            if hits:
                for hit in hits:
                    if hit not in recognized:
                        recognized.append(hit)
            else:
                unknown.append(cleaned)
        return recognized, unknown, tokens

    def infer_recipient(
        self,
        scene_value: str,
        explicit: Recipient | None,
        free_text: str | None,
        preference_tokens: list[str] | None = None,
    ) -> Recipient | None:
        """推断送礼对象。

        显式传参优先；否则从访客的自由描述里找关键词。
        访客经常把"送给长辈"写进偏好描述里，所以偏好原文也要一起看。
        """
        if explicit is not None:
            return explicit

        haystack = " ".join([free_text or "", *(preference_tokens or [])]).strip()
        if haystack:
            hits = self._match_keywords(haystack, RECIPIENT_KEYWORDS)
            if hits:
                return Recipient(hits[0])

        if scene_value == "self":
            return Recipient.SELF
        return None

    # ---------- 主入口 ----------
    def normalize(self, request: RecommendRequest) -> IntentExtraction:
        warnings: list[str] = []

        low, high, display = self.parse_budget(request.budget)
        if request.budget is not None and display is None:
            warnings.append("预算没看明白，本次按不限预算推荐")
            low = high = None

        preferences, unknown, tokens = self.normalize_preferences(
            request.preference, request.free_text
        )
        recipient = self.infer_recipient(
            request.scene.value, request.recipient, request.free_text, tokens
        )

        if recipient is not None and len(str(recipient.value)) > self.settings.max_recipient_chars:
            recipient = None

        intent = NormalizedIntent(
            scene=request.scene,
            scene_label=SCENE_LABELS.get(request.scene.value, request.scene.value),
            recipient=recipient,
            recipient_label=RECIPIENT_LABELS.get(recipient.value) if recipient else None,
            budget_min_yuan=low,
            budget_max_yuan=high,
            budget_display=display,
            preferences=preferences,
            preference_labels=[PREFERENCE_LABELS.get(item, item) for item in preferences],
            excluded_product_id=request.excluded_product_id,
            unknown_preferences=unknown,
        )
        return IntentExtraction(intent=intent, warnings=warnings)
