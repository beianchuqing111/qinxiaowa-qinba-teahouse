"""领域枚举。

与前端约定的取值集中在这里，前端可直接调 GET /api/scenes 拿到中文标签，
避免两端各写一份硬编码导致对不上。
"""

from __future__ import annotations

from enum import Enum


class Scene(str, Enum):
    """入店需求场景（对应前端三个入口）。"""

    SELF = "self"                    # 自用
    GIFT = "gift"                    # 礼赠
    ANKANG_INTRO = "ankang_intro"    # 了解安康


class Recipient(str, Enum):
    """送礼对象。自用场景可不填。"""

    SELF = "self"
    ELDER = "elder"        # 长辈
    PARENT = "parent"      # 父母
    FRIEND = "friend"      # 朋友 / 同事
    CLIENT = "client"      # 客户 / 商务
    PARTNER = "partner"    # 伴侣
    KID = "kid"            # 孩子 / 晚辈


class Preference(str, Enum):
    """口味 / 偏好标签（可多选）。"""

    GREEN_TEA = "green_tea"        # 绿茶
    BLACK_TEA = "black_tea"        # 红茶
    DARK_TEA = "dark_tea"          # 黑茶 / 茯茶
    WHITE_TEA = "white_tea"        # 白茶
    LIGHT = "light"                # 清淡
    RICH = "rich"                  # 醇厚
    SWEET_AROMA = "sweet_aroma"    # 甜香
    FLORAL = "floral"              # 花香
    GIFT_READY = "gift_ready"      # 需要礼盒包装
    PORTABLE = "portable"          # 便携 / 办公
    HEALTHY = "healthy"            # 无糖无添加
    BEGINNER = "beginner"          # 喝茶不多，易入口


class ReviewStatus(str, Enum):
    """商品文化资料审核状态。未过审商品一律不进推荐池。"""

    APPROVED = "approved"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"


class PurchaseMode(str, Enum):
    """购买出口模式，决定前端是否出现跳转按钮。"""

    EXTERNAL_LINK = "external_link"    # 已接入真实店铺，明示跳转
    DISPLAY_ONLY = "display_only"      # 未接入，仅展示资料，不伪装下单


class RecommendResult(str, Enum):
    """推荐结果状态。"""

    OK = "ok"
    NO_MATCH = "no_match"
    NO_OTHER_MATCH = "no_other_match"


class DialogueSource(str, Enum):
    """对白来源，前端可在调试面板显示。"""

    TEMPLATE = "template"      # 内置模板（稳定兜底）
    LLM = "llm"                # 大模型改写后通过事实护栏
    LLM_REJECTED = "llm_rejected"  # 大模型输出未过护栏，已回退模板


# 中文标签表：接口直接下发，前端不再自己维护映射
SCENE_LABELS: dict[str, str] = {
    Scene.SELF.value: "自用",
    Scene.GIFT.value: "礼赠",
    Scene.ANKANG_INTRO.value: "了解安康",
}

RECIPIENT_LABELS: dict[str, str] = {
    Recipient.SELF.value: "自己",
    Recipient.ELDER.value: "长辈",
    Recipient.PARENT.value: "父母",
    Recipient.FRIEND.value: "朋友或同事",
    Recipient.CLIENT.value: "客户或商务",
    Recipient.PARTNER.value: "伴侣",
    Recipient.KID.value: "孩子或晚辈",
}

PREFERENCE_LABELS: dict[str, str] = {
    Preference.GREEN_TEA.value: "绿茶",
    Preference.BLACK_TEA.value: "红茶",
    Preference.DARK_TEA.value: "黑茶茯茶",
    Preference.WHITE_TEA.value: "白茶",
    Preference.LIGHT.value: "清淡",
    Preference.RICH.value: "醇厚",
    Preference.SWEET_AROMA.value: "甜香",
    Preference.FLORAL.value: "花香",
    Preference.GIFT_READY.value: "礼盒装",
    Preference.PORTABLE.value: "便携",
    Preference.HEALTHY.value: "无添加",
    Preference.BEGINNER.value: "易入口",
}


def label_of(mapping: dict[str, str], value: str | None, fallback: str = "") -> str:
    if not value:
        return fallback
    return mapping.get(value, value)
