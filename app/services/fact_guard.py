"""事实护栏（Fact Guard）。

对应分工方案："可接大模型生成简短对白，但不得编造产地、检测、价格或链接"、
"从资料字段读取图片、规格、价格与产地；缺少依据就明确说明"。

护栏在"大模型输出 -> 访客可见"之间做一次硬校验，任意一条不通过就整段丢弃、
回退到模板对白。校验三类风险：

  1. 数字幻觉：出现资料库里没有的数字（价格、克重、含量、年份、检测值）
  2. 资质与功效幻觉：出现"检测合格/有机认证/获奖/疗效"等未经核验的表述
  3. 产地幻觉：出现资料库未记录的具体地名（县/镇/乡/村）

同时允许"明确的否定表述"，例如"这款商品暂时没有提供检测报告"是合规的——
因为它没有创造事实，反而是在说明资料缺失。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.product import Product

# ---------- 词表 ----------
CERTAINTY_CLAIM_WORDS: tuple[str, ...] = (
    "检测报告", "检测合格", "质检", "农残", "有机认证", "有机", "认证", "资质",
    "获奖", "金奖", "第一名", "特级认证", "国标", "地理标志", "专利",
)

HEALTH_CLAIM_WORDS: tuple[str, ...] = (
    "治疗", "疗效", "预防疾病", "抗癌", "降压", "降血糖", "降血脂", "减肥", "排毒",
    "包治", "药效", "养生功效", "延年益寿", "提高免疫",
)

ABSOLUTE_WORDS: tuple[str, ...] = (
    "最好", "第一", "顶级", "唯一", "绝对", "百分之百", "100%", "全网最低",
)

COMPONENT_WORDS: tuple[str, ...] = (
    "富硒含量", "硒含量", "含量为", "mg/kg", "毫克每千克", "微克",
)

ORIGIN_PATTERN = re.compile(r"[\u4e00-\u9fa5]{1,6}(?:县|镇|乡|村|区|市|州)")
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
YEAR_PATTERN = re.compile(r"(?:1[89]\d{2}|20\d{2})\s*年")
NEGATION_WORDS: tuple[str, ...] = (
    "未", "没有", "暂无", "无", "不是", "不", "尚未", "缺", "非", "不对外", "得", "待",
)

# 结构性数字：只用于计数"一两款"，不构成事实，允许通过
STRUCTURAL_NUMBERS = {"0", "1", "2", "3"}

# 地名词后缀
PLACE_SUFFIXES = ("县", "镇", "乡", "村", "区", "市", "州")


def place_variants(token: str, max_prefix: int = 5) -> set[str]:
    """把一个"疑似地名"拆成若干以地名词后缀结尾的候选写法。

    正则只能给出一个大致的字符窗口（例如从 "产地是陕西省安康市紫阳县"
    里可能切出 "是陕西省安康市"），所以这里按后缀位置向右对齐切分，
    只要其中任意一种写法在资料库里出现过，就认为这个地名是有依据的。
    """
    variants: set[str] = set()
    for index, char in enumerate(token):
        if char in PLACE_SUFFIXES and index >= 1:
            start = max(0, index - max_prefix)
            for cursor in range(start, index):
                variants.add(token[cursor : index + 1])
    return variants


@dataclass
class Violation:
    kind: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "detail": self.detail}


@dataclass
class GuardResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    checked_text: str = ""

    def reason(self) -> str:
        if self.ok:
            return ""
        return "；".join(f"{item.kind}: {item.detail}" for item in self.violations)


class FactGuard:
    """以单个商品的可核验事实为白名单，校验一段待展示文案。"""

    def __init__(self, product: Product) -> None:
        self.product = product
        self.digest: dict[str, Any] = product.fact_digest()
        # 顺序有依赖：白名单都基于 _source_text 构建，必须先算它
        self._source_text = self._collect_source_text()
        self._allowed_numbers = self._collect_allowed_numbers()
        self._allowed_places = self._collect_allowed_places()

    # ---------- 白名单构建 ----------
    def _collect_source_text(self) -> str:
        digest = self.digest
        pieces: list[str] = [str(digest.get("name") or "")]
        if digest.get("price_display"):
            pieces.append(str(digest["price_display"]))
        pieces.extend(str(item) for item in digest.get("spec_values") or [])
        if digest.get("origin"):
            pieces.append(str(digest["origin"]))
        pieces.extend(str(item) for item in digest.get("culture_paragraphs") or [])
        pieces.extend(str(item) for item in digest.get("culture_facts") or [])
        if digest.get("shop_platform"):
            pieces.append(str(digest["shop_platform"]))
        pieces.extend(self.product.missing_facts)
        for spec in self.product.specs:
            pieces.append(f"{spec.label}{spec.value}")
        return " ".join(pieces)

    def _collect_allowed_numbers(self) -> set[str]:
        numbers: set[str] = set()
        for match in NUMBER_PATTERN.finditer(self._source_text):
            numbers.add(match.group())
            # "12800 分" 同时允许 "128" / "128.00" 这些自然写法
            value = match.group()
            if "." in value:
                numbers.add(value.split(".")[0])
        price = self.product.price
        if price.verified:
            numbers.add(str(price.amount_cents))
            numbers.add(f"{price.amount_yuan:g}")
            numbers.add(f"{price.amount_cents / 100:.2f}")
        return numbers

    def _collect_allowed_places(self) -> set[str]:
        places: set[str] = set()
        for match in ORIGIN_PATTERN.finditer(self._source_text):
            places |= place_variants(match.group())
            # 允许"紫阳"这种去掉后缀的简称
            places.add(match.group()[:-1])
        return {item for item in places if len(item) >= 2}

    # ---------- 校验 ----------
    @staticmethod
    def _is_negated(text: str, start: int, window: int = 12) -> bool:
        prefix = text[max(0, start - window) : start]
        return any(word in prefix for word in NEGATION_WORDS)

    def _check_numbers(self, text: str) -> list[Violation]:
        violations: list[Violation] = []
        for match in NUMBER_PATTERN.finditer(text):
            token = match.group()
            if token in self._allowed_numbers or token in STRUCTURAL_NUMBERS:
                continue
            if self._is_negated(text, match.start()):
                continue
            violations.append(
                Violation("数字幻觉", f"出现资料库中没有的数字「{token}」，已阻止展示")
            )
        for match in YEAR_PATTERN.finditer(text):
            if match.group().strip() not in self._source_text:
                violations.append(
                    Violation("年份幻觉", f"出现资料库中没有的年份「{match.group().strip()}」")
                )
        return violations

    def _check_word_table(
        self, text: str, words: tuple[str, ...], kind: str, message: str
    ) -> list[Violation]:
        violations: list[Violation] = []
        lowered = text.lower()
        for word in words:
            index = lowered.find(word.lower())
            if index < 0:
                continue
            if word in self._source_text:
                continue
            if self._is_negated(text, index):
                continue
            violations.append(Violation(kind, message.format(word=word)))
        return violations

    def _check_component(self, text: str) -> list[Violation]:
        violations: list[Violation] = []
        lowered = text.lower()
        for word in COMPONENT_WORDS:
            index = lowered.find(word.lower())
            if index < 0:
                continue
            if word.lower() in self._source_text.lower():
                continue
            if self._is_negated(text, index):
                continue
            violations.append(
                Violation("成分含量幻觉", f"资料未提供成分含量，不允许出现「{word}」")
            )
        return violations

    def _check_places(self, text: str) -> list[Violation]:
        violations: list[Violation] = []
        for match in ORIGIN_PATTERN.finditer(text):
            place = match.group()
            if place in self._source_text or place in self._allowed_places:
                continue
            if place_variants(place) & self._allowed_places:
                continue
            if self._is_negated(text, match.start()):
                continue
            violations.append(
                Violation("产地幻觉", f"资料未记录地名「{place}」，不允许写入对白")
            )
        return violations

    def validate(self, text: str) -> GuardResult:
        """校验一段文案。ok=False 时调用方必须回退模板。"""
        candidate = (text or "").strip()
        if not candidate:
            return GuardResult(False, [Violation("空文案", "大模型没有返回有效内容")], candidate)

        violations: list[Violation] = []
        violations += self._check_numbers(candidate)
        violations += self._check_word_table(
            candidate, CERTAINTY_CLAIM_WORDS, "资质幻觉",
            "资料未提供「{word}」相关证明，不允许对外宣称",
        )
        violations += self._check_word_table(
            candidate, HEALTH_CLAIM_WORDS, "功效违规",
            "「{word}」属于功效性表述，不允许出现在茶舍对白中",
        )
        violations += self._check_word_table(
            candidate, ABSOLUTE_WORDS, "绝对化用语",
            "「{word}」属于绝对化用语，不允许使用",
        )
        violations += self._check_component(candidate)
        violations += self._check_places(candidate)
        return GuardResult(ok=not violations, violations=violations, checked_text=candidate)

    def allowed_fact_brief(self, max_chars: int = 700) -> str:
        """给大模型的"允许事实"清单。模型只能改写这些内容。"""
        digest = self.digest
        lines = [f"商品名称：{digest['name']}"]
        if digest.get("price_display"):
            lines.append(f"价格：{digest['price_display']}（已核验）")
        if digest.get("spec_values"):
            lines.append("规格：" + "；".join(str(item) for item in digest["spec_values"]))
        if digest.get("origin"):
            lines.append(f"产地：{digest['origin']}（已核验）")
        if digest.get("culture_facts"):
            lines.append("文化卡事实点：" + "；".join(str(item) for item in digest["culture_facts"]))
        if digest.get("culture_paragraphs"):
            lines.append("文化背景：" + " ".join(str(item) for item in digest["culture_paragraphs"]))
        if digest.get("shop_platform"):
            lines.append(f"购买出口：已接入 {digest['shop_platform']}")
        else:
            lines.append("购买出口：未接入线上店铺，只能展示资料")
        if self.product.missing_facts:
            lines.append("资料缺失（只能说明缺失，不能编造）：" + "；".join(self.product.missing_facts))
        brief = "\n".join(lines)
        return brief[:max_chars]
