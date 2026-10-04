from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SCENES = [
    {"id": "water", "name": "水源", "title": "山泉瀑布", "local": True, "product_count": 13},
    {"id": "tea", "name": "茶社", "title": "云雾茶园", "local": True, "product_count": 4},
    {"id": "farm", "name": "田园", "title": "林下魔芋田", "local": True, "product_count": 3},
    {"id": "kitchen", "name": "灶房", "title": "村舍炊烟", "local": True, "product_count": 2},
    {"id": "station", "name": "驿铺", "title": "江边驿站", "local": False, "product_count": 16},
    {"id": "market", "name": "杂货", "title": "街边杂货铺", "local": False, "product_count": 21},
    {"id": "vanity", "name": "妆台", "title": "绣楼妆台", "local": False, "product_count": 13},
]

STAGES = [
    {"id": "water-trail", "scene": "water", "name": "山水寻踪", "seal": "山水印", "question": "如果只有半天时间，你更想怎么走？", "options": ["沿水慢慢走", "登高看看秦巴山色"]},
    {"id": "local-flavor", "scene": "tea", "name": "风物探秘", "seal": "风物印", "question": "认识富硒产品时，最重要的是看什么？", "options": ["夸张的功效宣传", "来源、信息依据和使用场景"]},
    {"id": "good-things", "scene": "station", "name": "好物寻味", "seal": "好物印", "question": "你想把什么带回去？", "options": ["给朋友的伴手礼", "秦巴味道和地方好物"]},
]

PRODUCTS = [
    {"id": "water-bottle-330", "scene": "water", "name": "秦巴山泉 330ml 瓶装水", "brand": "演示品牌", "origin": "安康秦巴", "price_cents": 500, "spec": "330ml", "selenium": "以核验报告为准", "report_id": "DEMO-W-001", "purchase_url": "https://example.com/products/water-bottle-330", "tags": ["便携", "饮用"], "verified": True},
    {"id": "water-gift", "scene": "water", "name": "秦巴山泉礼盒", "brand": "演示品牌", "origin": "安康秦巴", "price_cents": 9900, "spec": "组合装", "selenium": "以核验报告为准", "report_id": "DEMO-W-002", "purchase_url": "https://example.com/products/water-gift", "tags": ["送礼", "礼盒"], "verified": True},
    {"id": "tea-gift", "scene": "tea", "name": "秦巴风物茶礼盒", "brand": "演示茶社", "origin": "安康秦巴", "price_cents": 12900, "spec": "礼盒装", "selenium": "以核验报告为准", "report_id": "DEMO-T-001", "purchase_url": "https://example.com/products/tea-gift", "tags": ["茶", "送礼"], "verified": True},
    {"id": "konjac-snack", "scene": "farm", "name": "秦巴魔芋风味组合", "brand": "演示田园", "origin": "陕西秦巴", "price_cents": 6900, "spec": "组合装", "selenium": "不展示未经核验的数值", "report_id": "DEMO-F-001", "purchase_url": "https://example.com/products/konjac-snack", "tags": ["零食", "伴手礼"], "verified": True},
    {"id": "local-gift", "scene": "station", "name": "秦巴地方好物伴手礼", "brand": "演示驿铺", "origin": "秦巴地区", "price_cents": 15900, "spec": "礼盒装", "selenium": "以核验报告为准", "report_id": "DEMO-S-001", "purchase_url": "https://example.com/products/local-gift", "tags": ["伴手礼", "送礼"], "verified": True},
]

FACTS = {p["id"]: p for p in PRODUCTS}
KNOWLEDGE = [
    {"id": "kb-001", "text": "安康秦巴山水、茶园和地方风物是硒游记的内容背景。区域背景不等于某个商品的检测结论。", "source": "team-curated-demo", "kind": "region"},
    {"id": "kb-002", "text": "理解富硒产品时，应关注产品来源、信息依据、适用场景和核验状态，不把夸张功效宣传当作证据。", "source": "team-curated-demo", "kind": "compliance"},
    {"id": "kb-003", "text": "硒游记文牒代表线上互动探索完成，不代表用户实际到访景点。", "source": "xiyouji-proposal", "kind": "experience"},
]

BANNED = re.compile(r"抗癌|防癌|治病|根治|降三高|改善睡眠|治疗|疗效|全民补硒|越高越好|治愈")


def search_knowledge(query: str, limit: int = 4) -> list[dict[str, Any]]:
    words = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
    scored = []
    for item in KNOWLEDGE:
        score = sum(1 for word in words if word and word in item["text"].lower())
        if score or not words:
            scored.append((score, item))
    return [item for _, item in sorted(scored, key=lambda x: -x[0])[:limit]]


def search_products(query: str = "", scene: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
    q = query.lower()
    result = []
    for product in PRODUCTS:
        if scene and product["scene"] != scene:
            continue
        haystack = " ".join([product["name"], product["brand"], product["origin"], *product["tags"]]).lower()
        if q and not any(token in haystack for token in re.findall(r"[\w\u4e00-\u9fff]+", q)):
            continue
        result.append(product)
    return result[:limit]


def sanitize(text: str) -> tuple[str, bool]:
    if BANNED.search(text):
        return "我不能把普通食品描述为具有治疗或保健功效。建议查看产品来源、适用场景和核验信息，再按实际需要选择。", True
    return text, False


@dataclass
class HybridKnowledgeBase:
    """Hybrid retrieval: exact structured facts first, text knowledge second."""

    def retrieve(self, query: str, scene: str | None = None) -> dict[str, Any]:
        products = search_products(query, scene)
        docs = search_knowledge(query)
        return {"products": products, "documents": docs}
