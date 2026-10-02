"""外链安全与降级兜底测试。

对应分工方案：
  - "校验外链目标，并控制异常、超时与可演示兜底"
  - "外链标注'前往淘宝/店铺购买'，跳转与所选商品相符；未接入时无假下单"
"""

from __future__ import annotations

import asyncio

import pytest

from app.api.deps import Container
from app.core.security import ShopLinkGuard
from app.models.api_schemas import RecommendRequest
from app.services.fact_guard import FactGuard
from app.services.llm import LlmResult


# ---------- 外链校验 ----------
def test_whitelist_empty_means_display_only(settings_factory):
    guard = ShopLinkGuard(settings_factory(shop_link_allowed_hosts=[]))
    decision = guard.evaluate("https://item.taobao.com/item.htm?id=1")
    assert decision.allowed is False
    assert "白名单" in (decision.reason or "")


def test_whitelist_allows_https_on_exact_host(settings_factory):
    guard = ShopLinkGuard(settings_factory(shop_link_allowed_hosts=["item.taobao.com"]))
    assert guard.evaluate("https://item.taobao.com/item.htm?id=1").allowed is True


def test_whitelist_allows_subdomain(settings_factory):
    guard = ShopLinkGuard(settings_factory(shop_link_allowed_hosts=["taobao.com"]))
    assert guard.evaluate("https://item.taobao.com/item.htm?id=1").allowed is True


def test_whitelist_rejects_other_host(settings_factory):
    guard = ShopLinkGuard(settings_factory(shop_link_allowed_hosts=["item.taobao.com"]))
    assert guard.evaluate("https://evil.example.com/item?id=1").allowed is False


@pytest.mark.parametrize(
    "url",
    [
        "http://item.taobao.com/item.htm?id=1",                    # 非 https
        "javascript:alert(1)",                                      # 危险协议
        "data:text/html;base64,PHNjcmlwdD4=",                       # 危险协议
        "https://user:pwd@item.taobao.com/item.htm",                 # 携带账号信息
        "https://127.0.0.1/item.htm",                                # 直连 IP
        "https://item.taobao.com/item.htm?url=https://evil.com",     # 疑似开放重定向
        "",                                                          # 空值
        None,
    ],
)
def test_dangerous_links_are_always_blocked(settings_factory, url):
    guard = ShopLinkGuard(settings_factory(shop_link_allowed_hosts=["item.taobao.com"]))
    assert guard.evaluate(url).allowed is False


def test_outbound_endpoint_blocks_when_not_connected(client):
    body = client.get("/api/outbound/QBT-002").json()
    assert body["allowed"] is False
    assert body["url"] is None
    assert body["purchase_mode"] == "display_only"
    assert "未接入" in body["message"] or "白名单" in body["message"]


def test_outbound_endpoint_allows_when_whitelisted(whitelist_client):
    body = whitelist_client.get("/api/outbound/QBT-002").json()
    assert body["allowed"] is True
    assert body["purchase_mode"] == "external_link"
    assert body["host"] == "item.taobao.com"
    assert "跳转" in body["message"]

    check = whitelist_client.get("/api/outbound/QBT-002/check").json()
    assert check["whitelist"] == ["item.taobao.com"]


def test_recommendation_exposes_link_only_when_whitelisted(whitelist_client):
    body = whitelist_client.post(
        "/api/recommend",
        json={"scene": "gift", "recipient": "elder", "budget": 300, "preference": ["gift_ready"]},
    ).json()
    rec = body["recommendation"]
    assert rec["product_id"] == "QBT-002", "礼盒偏好的礼盒款应被选中"
    assert rec["purchase_mode"] == "external_link"
    assert rec["shop_link"]["url"].startswith("https://")
    assert rec["shop_link_note"] is None, "已接入时不应出现未接入说明"
    assert any("已接入" in point for point in rec["reason_points"])


# ---------- 大模型降级 ----------
def test_llm_disabled_falls_back_to_template(client):
    body = client.post("/api/recommend", json={"scene": "self"}).json()
    assert body["meta"]["dialogue_source"] == "template"
    assert body["meta"]["degraded"] is False
    assert body["recommendation"]["dialogue"]


def test_llm_failure_degrades_without_breaking_demo(settings_factory, monkeypatch):
    """把大模型打开但让它必然失败，验证仍能返回合规的模板对白。"""
    container = Container(settings_factory(llm_enabled=True, llm_api_key="fake-key"))

    async def always_fail(_prompt: str) -> None:
        return None

    monkeypatch.setattr(container.llm, "rewrite_dialogue", always_fail)

    product = container.catalog.get_approved("QBT-001")
    intent = container.intent.normalize(RecommendRequest(scene="self")).intent
    result = asyncio.run(container.dialogue.compose(product, intent))

    assert result.dialogue
    assert result.degraded is True
    assert "内置" in (result.degraded_reason or "")
    assert FactGuard(product).validate(result.dialogue).ok


def test_llm_hallucination_is_rejected_and_falls_back(settings_factory, monkeypatch):
    """模型编造资质与含量时必须被拦下，访客看到的仍是模板对白。"""
    container = Container(settings_factory(llm_enabled=True, llm_api_key="fake-key"))

    async def hallucinate(_prompt: str) -> LlmResult:
        return LlmResult(text="这款茶通过了有机认证，检测合格，富含硒 42 毫克，是最好的。", model="fake")

    monkeypatch.setattr(container.llm, "rewrite_dialogue", hallucinate)

    product = container.catalog.get_approved("QBT-001")
    intent = container.intent.normalize(RecommendRequest(scene="self")).intent
    result = asyncio.run(container.dialogue.compose(product, intent))

    assert result.source.value == "llm_rejected"
    assert result.degraded is True
    assert "有机" not in result.dialogue
    assert "42" not in result.dialogue
    assert FactGuard(product).validate(result.dialogue).ok


def test_llm_clean_rewrite_is_accepted(settings_factory, monkeypatch):
    """模型输出合规时应被采纳，并标记来源为 llm。"""
    container = Container(settings_factory(llm_enabled=True, llm_api_key="fake-key"))

    async def good(_prompt: str) -> LlmResult:
        return LlmResult(text="自己喝的话，我挑这款紫阳的毛尖。茶汤清亮，入口清淡回甘，慢慢泡正合适。", model="fake")

    monkeypatch.setattr(container.llm, "rewrite_dialogue", good)

    product = container.catalog.get_approved("QBT-001")
    intent = container.intent.normalize(RecommendRequest(scene="self")).intent
    result = asyncio.run(container.dialogue.compose(product, intent))

    assert result.source.value == "llm"
    assert result.dialogue.startswith("自己喝的话")
    assert result.degraded is False


# ---------- 资料库异常兜底 ----------
def test_catalog_failure_falls_back_to_last_good_snapshot(settings_factory, tmp_path):
    """资料库文件被写坏时，应使用上次成功快照，而不是整体 500。"""
    broken = tmp_path / "products.json"
    broken.write_text('{"products": []}', encoding="utf-8")

    container = Container(settings_factory(catalog_json_path=str(broken)))
    assert container.catalog.load().products == []

    broken.write_text("{ this is not json", encoding="utf-8")
    container.catalog.invalidate()
    snapshot = container.catalog.load()

    assert snapshot.degraded is True
    assert "最近一次成功加载" in (snapshot.degraded_reason or "")


def test_sqlite_backend_missing_file_falls_back_to_seed(settings_factory, tmp_path):
    container = Container(
        settings_factory(
            catalog_backend="sqlite",
            catalog_sqlite_path=str(tmp_path / "not-created.db"),
        )
    )
    snapshot = container.catalog.load()
    assert snapshot.degraded is True
    assert snapshot.approved, "应回退到种子 JSON，保证演示可继续"
