"""对外接口的请求 / 响应模型（前后端交接契约）。

与分工方案第 03 节保持一致：
POST /api/recommend
  请求：scene, recipient, budget, preference, excluded_product_id
  返回：商品 ID、名称、图片、价格与规格、简短对白、推荐理由、
        文化卡、来源状态、店铺链接（若已接入）
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    DialogueSource,
    Preference,
    Recipient,
    RecommendResult,
    Scene,
)


class BudgetIn(BaseModel):
    """预算。三种写法都接受，服务端统一归一化成区间（单位：元）。"""

    model_config = ConfigDict(extra="forbid")

    min: float | None = Field(default=None, ge=0, le=100000, description="预算下限（元）")
    max: float | None = Field(default=None, ge=0, le=100000, description="预算上限（元）")

    @model_validator(mode="after")
    def _check_range(self) -> "BudgetIn":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("预算下限不能大于上限")
        return self


class RecommendRequest(BaseModel):
    """首次推荐 / 换一款 共用的请求体。

    兼容前端三种常见传法：
      "budget": 200                 -> 上限 200
      "budget": "100-300"           -> 区间
      "budget": {"min": 100, "max": 300}
    """

    model_config = ConfigDict(extra="forbid")

    scene: Scene = Field(description="需求场景：self 自用 / gift 礼赠 / ankang_intro 了解安康")
    recipient: Recipient | None = Field(default=None, description="送礼对象，自用可不填")
    budget: BudgetIn | float | int | str | None = Field(default=None, description="预算（元），支持数字或 '100-300'")
    preference: list[str] | str | None = Field(default=None, description="口味偏好，支持数组或一段中文描述")
    excluded_product_id: str | None = Field(
        default=None, description="换一款时传当前商品 ID，服务端会避开它"
    )
    session_id: str | None = Field(default=None, max_length=64, description="会话 ID，用于记住当前商品")
    free_text: str | None = Field(
        default=None, max_length=200, description="访客补充说明，仅做关键词提取，不参与事实生成"
    )

    @field_validator("preference", mode="before")
    @classmethod
    def _normalize_preference(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            parts = [p.strip() for p in value.replace("，", ",").replace("、", ",").split(",")]
            return [p for p in parts if p]
        return value

    @field_validator("excluded_product_id", "session_id", "free_text", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class NormalizedIntent(BaseModel):
    """服务端归一化后的需求，会随响应回传，便于前端展示"我理解成了什么"。"""

    scene: Scene
    scene_label: str
    recipient: Recipient | None = None
    recipient_label: str | None = None
    budget_min_yuan: float | None = None
    budget_max_yuan: float | None = None
    budget_display: str | None = None
    preferences: list[str] = Field(default_factory=list)
    preference_labels: list[str] = Field(default_factory=list)
    excluded_product_id: str | None = None
    unknown_preferences: list[str] = Field(default_factory=list)


class RecommendationOut(BaseModel):
    """单款推荐结果。字段名即前端渲染字段。"""

    model_config = ConfigDict(populate_by_name=True)

    product_id: str
    name: str
    subtitle: str | None = None
    image_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    price: dict[str, Any] = Field(default_factory=dict)      # {amount_cents, display, unit, verified}
    specs: list[dict[str, Any]] = Field(default_factory=list)
    dialogue: str = Field(description="两三句简短对白（受事实护栏约束）")
    reason: str = Field(description="推荐理由，仅引用已核验字段")
    reason_points: list[str] = Field(default_factory=list)
    culture_card: dict[str, Any] = Field(default_factory=dict)
    source_status: dict[str, Any] = Field(default_factory=dict)
    shop_link: dict[str, Any] | None = Field(default=None, description="未接入时为 null")
    purchase_mode: str
    shop_link_note: str | None = Field(
        default=None, description="未接入线上店铺时的说明，前端据此渲染提示文案"
    )
    missing_facts: list[str] = Field(default_factory=list)
    match_score: int = 0


class RecommendMeta(BaseModel):
    """诊断信息，前端可折叠展示，方便联调与现场排障。"""

    trace_id: str
    dialogue_source: DialogueSource = DialogueSource.TEMPLATE
    degraded: bool = False
    degraded_reason: str | None = None
    notes: list[str] = Field(
        default_factory=list, description="过程说明（如未接入外链、放宽了约束），不属于故障"
    )
    relaxed: bool = False
    relaxed_reason: str | None = None
    catalog_backend: str = "json"
    candidate_count: int = 0
    eligible_count: int = 0
    elapsed_ms: int = 0


class RecommendResponse(BaseModel):
    result: RecommendResult
    message: str
    intent: NormalizedIntent
    recommendation: RecommendationOut | None = None
    alternatives_available: bool = False
    meta: RecommendMeta


class ProductSummary(BaseModel):
    product_id: str
    name: str
    subtitle: str | None = None
    category: str
    image_url: str | None = None
    price_display: str
    price_verified: bool
    review_status: str
    purchase_mode: str
    scenes: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class ProductListResponse(BaseModel):
    total: int
    items: list[ProductSummary]


class ProductDetailResponse(BaseModel):
    product: dict[str, Any]
    source_status: dict[str, Any]
    shop_link: dict[str, Any] | None = None
    purchase_mode: str
    missing_facts: list[str] = Field(default_factory=list)


class OutboundLinkResponse(BaseModel):
    """查看 / 离站：只返回有来源、且在白名单内的链接。"""

    product_id: str
    allowed: bool
    purchase_mode: str
    url: str | None = None
    label: str | None = None
    host: str | None = None
    message: str


class SceneOptionOut(BaseModel):
    value: str
    label: str
    description: str = ""


class OptionGroupOut(BaseModel):
    scenes: list[SceneOptionOut]
    recipients: list[SceneOptionOut]
    preferences: list[SceneOptionOut]
    budget_hints: list[dict[str, Any]]
    demo_cases: list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: str
    version: str
    env: str
    catalog_backend: str
    catalog_ready: bool
    approved_product_count: int
    llm_enabled: bool
    llm_ready: bool
    outbound_link_whitelist: list[str]
