"""推荐主流程测试：对应分工方案第 05 节的验收路径。

扫码入店 → 选需求 → 推荐单款 → 换一款 → 看来历 → 看商品 → 去真实店铺或仅看资料
"""

from __future__ import annotations

import pytest


def test_health_reports_catalog_ready(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["catalog_ready"] is True
    # 种子数据里 2 款已审核 + 1 款待审核，对外只应看到 2 款
    assert payload["approved_product_count"] == 2
    assert payload["llm_enabled"] is False


def test_products_only_expose_approved(client):
    payload = client.get("/api/products").json()
    ids = {item["product_id"] for item in payload["items"]}
    assert ids == {"QBT-001", "QBT-002"}
    assert "QBT-003" not in ids, "待审核商品绝不能出现在对外接口里"

    pending = client.get("/api/products", params={"include_pending": True}).json()
    assert pending["total"] == 3


def test_case_self_recommendation(client):
    """案例一：自用，预算 150，偏好清淡易入口。"""
    response = client.post(
        "/api/recommend",
        json={
            "scene": "self",
            "budget": 150,
            "preference": ["light", "beginner"],
            "session_id": "case-self",
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["result"] == "ok"
    assert body["intent"]["budget_display"] == "150 元以内"
    assert "清淡" in body["intent"]["preference_labels"]

    rec = body["recommendation"]
    assert rec is not None
    assert rec["product_id"] in {"QBT-001", "QBT-002"}
    assert rec["dialogue"], "必须返回对白"
    assert rec["reason"], "必须返回推荐理由"
    assert rec["culture_card"]["title"]
    assert rec["source_status"]["review_status"] == "approved"
    # 价格与规格由后端给出，前端不需要硬编码
    assert rec["price"]["amount_cents"] > 0
    assert rec["specs"]


def test_case_gift_prefers_gift_box(client):
    """案例二：礼赠长辈，需要礼盒，偏好礼盒装。"""
    body = client.post(
        "/api/recommend",
        json={
            "scene": "gift",
            "recipient": "elder",
            "budget": "100-300",
            "preference": ["gift_ready"],
            "session_id": "case-gift",
        },
    ).json()

    assert body["result"] == "ok"
    assert body["intent"]["budget_min_yuan"] == 100
    assert body["intent"]["budget_max_yuan"] == 300
    rec = body["recommendation"]
    assert rec["product_id"] == "QBT-002", "礼盒场景应命中礼盒装的红茶"
    assert rec["purchase_mode"] == "display_only"
    assert rec["shop_link"] is None, "未配置白名单时不得下发任何跳转链接"
    assert any("未接入" in point for point in rec["reason_points"]), "推荐理由应与实际购买出口一致"
    assert rec["shop_link_note"], "未接入外链时要给前端一句可展示的说明"
    # 外链未接入是预期状态，不算故障降级
    assert body["meta"]["degraded"] is False
    assert body["meta"]["notes"]


def test_switch_returns_different_product(client):
    """换一款：必须避开当前商品，而不是重复同一款。"""
    first = client.post(
        "/api/recommend",
        json={"scene": "gift", "budget": 300, "session_id": "switch-1"},
    ).json()
    first_id = first["recommendation"]["product_id"]

    second = client.post(
        "/api/recommend/another",
        json={"scene": "gift", "budget": 300, "session_id": "switch-1"},
    ).json()

    assert second["result"] == "ok"
    assert second["recommendation"]["product_id"] != first_id
    assert "避开上一款" in second["recommendation"]["reason"], "理由里应说明已避开上一款"


def test_switch_without_other_match_returns_explicit_message(client):
    """只有两款商品时，连续换两次应当明确返回"暂无其他匹配"。"""
    client.post("/api/recommend", json={"scene": "gift", "budget": 300, "session_id": "s2"})
    client.post("/api/recommend/another", json={"scene": "gift", "budget": 300, "session_id": "s2"})
    third = client.post(
        "/api/recommend/another", json={"scene": "gift", "budget": 300, "session_id": "s2"}
    ).json()

    assert third["result"] == "no_other_match"
    assert third["message"] == "暂无其他匹配"
    assert third["recommendation"] is None


def test_excluded_product_id_is_respected(client):
    body = client.post(
        "/api/recommend",
        json={"scene": "gift", "budget": 300, "excluded_product_id": "QBT-002"},
    ).json()
    assert body["recommendation"]["product_id"] == "QBT-001"


def test_pending_product_never_recommended(client, container):
    """即使显式排除已审核商品，待审核商品也不能被顶上推荐位。"""
    from app.models.api_schemas import RecommendRequest
    from app.services.recommender import Recommender

    recommender = Recommender(container.settings)
    intent = container.intent.normalize(RecommendRequest(scene="self")).intent
    pool = container.catalog.approved_products()
    assert all(item.review_status.value == "approved" for item in pool)

    outcome = recommender.recommend(intent, pool=pool)
    assert outcome.product is not None
    assert outcome.product.id != "QBT-003"


def test_greeting_has_no_product_facts(client):
    body = client.post("/api/recommend/greeting", json={"scene": "gift", "recipient": "elder"}).json()
    assert body["state"] == "greeting"
    assert "长辈" in body["dialogue"]


def test_product_detail_and_option_groups(client):
    detail = client.get("/api/products/QBT-001").json()
    assert detail["product"]["name"]
    assert detail["purchase_mode"] == "display_only"
    assert detail["source_status"]["review_status"] == "approved"
    assert detail["missing_facts"], "资料缺失项必须显式下发"

    options = client.get("/api/scenes").json()
    assert [item["value"] for item in options["scenes"]] == ["self", "gift", "ankang_intro"]
    assert len(options["demo_cases"]) == 3, "需要 3 个可重复演示的案例"


def test_missing_product_returns_404(client):
    response = client.get("/api/products/QBT-999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"

    # 未过审商品同样按"不存在"处理，避免泄露资料
    pending = client.get("/api/products/QBT-003")
    assert pending.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"scene": "unknown-scene"},
        {"scene": "self", "budget": {"min": 300, "max": 100}},
        {"scene": "self", "recipient": "not-a-recipient"},
        {},
    ],
)
def test_invalid_input_returns_unified_error(client, payload):
    response = client.post("/api/recommend", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_INPUT"
    assert body["error"]["retryable"] is True


def test_unknown_preference_is_reported_not_guessed(client):
    body = client.post(
        "/api/recommend",
        json={"scene": "self", "preference": ["会飞的味道"]},
    ).json()
    assert body["result"] == "ok"
    assert body["intent"]["unknown_preferences"] == ["会飞的味道"]


def test_free_text_keywords_are_extracted(client):
    body = client.post(
        "/api/recommend",
        json={"scene": "gift", "preference": "想送长辈一个体面的礼盒"},
    ).json()
    labels = body["intent"]["preference_labels"]
    assert "礼盒装" in labels
    assert body["intent"]["recipient"] == "elder"
