"""商品 / 文化资料库的领域模型。

设计要点（对应分工方案"事实与内容安全"）：
1. 每一条可能被访客看到的事实（价格、规格、产地、检测、链接）都带 verified 标记，
   未核验的字段不会被读进推荐结果。
2. missing_facts 显式列出"资料未提供"的项，用于前端展示"暂无该信息"，
   而不是让模型去编造。
3. 金额一律用"分"存整数，避免浮点误差与前端硬编码。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import PurchaseMode, ReviewStatus


class PriceInfo(BaseModel):
    """价格。amount_cents 为整数分，display 直接给前端展示。"""

    amount_cents: int = Field(ge=0)
    currency: str = "CNY"
    unit: str = "份"
    verified: bool = False
    note: str | None = None

    @property
    def amount_yuan(self) -> float:
        return round(self.amount_cents / 100, 2)

    @property
    def display(self) -> str:
        yuan = self.amount_cents / 100
        text = f"¥{yuan:.2f}".rstrip("0").rstrip(".") if yuan % 1 else f"¥{int(yuan)}"
        return f"{text} / {self.unit}"


class SpecItem(BaseModel):
    """规格条目，例如 净含量=100g。"""

    label: str
    value: str
    verified: bool = True


class CultureCard(BaseModel):
    """产地文化卡：每款商品 1 张，全部内容必须有来源。"""

    title: str
    origin: str | None = None                 # 产地
    origin_verified: bool = False
    paragraphs: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)   # 短事实点，供对白引用
    verification_note: str | None = None      # 明确哪些表述不可使用
    sources: list[str] = Field(default_factory=list)


class SourceInfo(BaseModel):
    """资料来源与审核留痕。"""

    material_source: str = "待内容负责人补充"   # 素材来源
    reviewer: str | None = None                # 审核人
    reviewed_at: str | None = None             # 审核时间
    notes: str | None = None


class ShopLink(BaseModel):
    """购买出口。enabled=false 时前端不得出现跳转按钮。"""

    platform: str = "淘宝"
    url: str | None = None
    enabled: bool = False
    label: str | None = None    # 例如"前往淘宝查看同款"


class MatchTags(BaseModel):
    """用于受约束筛选的标签。缺字段即视为不匹配，不做猜测。"""

    scenes: list[str] = Field(default_factory=list)
    recipients: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class Product(BaseModel):
    """一款已录入商品。"""

    id: str
    name: str
    subtitle: str | None = None
    category: str = "茶"
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    price: PriceInfo
    specs: list[SpecItem] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    culture_card: CultureCard
    source: SourceInfo = Field(default_factory=SourceInfo)
    shop_link: ShopLink = Field(default_factory=ShopLink)
    tags: MatchTags = Field(default_factory=MatchTags)
    missing_facts: list[str] = Field(default_factory=list)  # 资料未提供、禁止编造的项
    sibling_ids: list[str] = Field(default_factory=list)    # 同系列可换款，仅作展示提示

    @field_validator("id")
    @classmethod
    def _clean_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("商品 id 不能为空")
        return value

    @property
    def is_approved(self) -> bool:
        return self.review_status == ReviewStatus.APPROVED

    @property
    def purchase_mode(self) -> PurchaseMode:
        """有可用外链才允许跳转，否则只能是展示模式。"""
        if self.shop_link.enabled and self.shop_link.url:
            return PurchaseMode.EXTERNAL_LINK
        return PurchaseMode.DISPLAY_ONLY

    def verified_spec_lines(self) -> list[str]:
        return [f"{item.label}：{item.value}" for item in self.specs if item.verified]

    def all_verified_spec_values(self) -> list[str]:
        return [item.value for item in self.specs if item.verified]

    def fact_digest(self) -> dict[str, Any]:
        """交给事实护栏的"允许事实"集合。

        只有出现在这里的数字/名称，才允许出现在最终对白里。
        """
        return {
            "name": self.name,
            "price_display": self.price.display if self.price.verified else None,
            "price_yuan": self.price.amount_yuan if self.price.verified else None,
            "unit": self.price.unit,
            "spec_values": self.all_verified_spec_values(),
            "origin": self.culture_card.origin if self.culture_card.origin_verified else None,
            "culture_paragraphs": list(self.culture_card.paragraphs),
            "culture_facts": list(self.culture_card.facts),
            "shop_platform": self.shop_link.platform if self.purchase_mode == PurchaseMode.EXTERNAL_LINK else None,
        }
