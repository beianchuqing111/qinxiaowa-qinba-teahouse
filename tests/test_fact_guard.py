"""事实护栏测试。

对应分工方案："推荐的商品、理由、价格、规格、文化来源彼此一致；无依据时不生成事实"。
这是后端最核心的安全边界，务必覆盖到位。
"""

from __future__ import annotations

import pytest

from app.models.api_schemas import RecommendRequest
from app.services.dialogue import DialogueService
from app.services.fact_guard import FactGuard
from app.services.llm import LlmClient


@pytest.fixture
def guard(container):
    product = container.catalog.get_approved("QBT-001")
    assert product is not None
    return FactGuard(product)


@pytest.fixture
def gift_guard(container):
    product = container.catalog.get_approved("QBT-002")
    assert product is not None
    return FactGuard(product)


# ---------- 数字幻觉 ----------
def test_allows_numbers_present_in_catalog(guard):
    verdict = guard.validate("这款是 100g 罐装，产地是陕西省安康市紫阳县，价格是¥128。")
    assert verdict.ok, verdict.reason()


def test_rejects_invented_number(guard):
    verdict = guard.validate("这款茶含有 42 毫克的硒，非常值得。")
    assert not verdict.ok
    assert any(item.kind == "数字幻觉" for item in verdict.violations)


def test_rejects_invented_year(guard):
    verdict = guard.validate("这款茶从 1893 年开始种植。")
    assert not verdict.ok


def test_allows_structural_counting(guard):
    verdict = guard.validate("目前茶舍里有两款已审核的茶，可以换一款试试。")
    assert verdict.ok, verdict.reason()


# ---------- 资质 / 功效 ----------
def test_rejects_certification_claim(guard):
    verdict = guard.validate("这款茶通过了有机认证，检测合格。")
    assert not verdict.ok
    kinds = {item.kind for item in verdict.violations}
    assert "资质幻觉" in kinds


def test_allows_explicit_absence_of_evidence(guard):
    """说"没有提供检测报告"是合规的：它没有创造事实。"""
    verdict = guard.validate("这款商品暂时没有提供检测报告，我就不替您打包票了。")
    assert verdict.ok, verdict.reason()


def test_rejects_health_claim(guard):
    verdict = guard.validate("常喝这款茶可以降血压、排毒养生。")
    assert not verdict.ok
    assert any(item.kind == "功效违规" for item in verdict.violations)


def test_rejects_absolute_wording(guard):
    verdict = guard.validate("这是安康最好的茶，全网最低价。")
    assert not verdict.ok
    assert any(item.kind == "绝对化用语" for item in verdict.violations)


def test_rejects_component_claim(guard):
    verdict = guard.validate("硒含量为 0.3，比普通茶更高。")
    assert not verdict.ok


# ---------- 产地幻觉 ----------
def test_allows_recorded_origin(guard):
    assert guard.validate("产地是陕西省安康市紫阳县。").ok


def test_rejects_unrecorded_place(guard):
    verdict = guard.validate("这批茶来自汉阴县凤凰山的老茶园。")
    assert not verdict.ok
    assert any(item.kind == "产地幻觉" for item in verdict.violations)


def test_rejects_unrecorded_place_for_gift_product(gift_guard):
    """礼盒款的产地明细未核验，任何具体乡镇都不允许出现。"""
    verdict = gift_guard.validate("这盒茶采自平利县八仙镇的茶园。")
    assert not verdict.ok


def test_empty_text_is_rejected(guard):
    assert not guard.validate("   ").ok


# ---------- 模板自身必须合规 ----------
@pytest.mark.parametrize("product_id,scene", [("QBT-001", "self"), ("QBT-002", "gift")])
def test_builtin_template_passes_guard(container, product_id, scene):
    """内置模板是对外兜底，必须 100% 通过自己的护栏。"""
    product = container.catalog.get_approved(product_id)
    intent = container.intent.normalize(
        RecommendRequest(scene=scene, budget=300, recipient="elder" if scene == "gift" else None)
    ).intent

    dialogue = DialogueService(container.settings, LlmClient(container.settings))
    result = dialogue.build_template(product, intent)
    verdict = FactGuard(product).validate(result.dialogue)
    assert verdict.ok, f"模板对白未通过护栏：{verdict.reason()}\n{result.dialogue}"


def test_allowed_fact_brief_contains_no_unverified_price(container):
    product = container.catalog.get_approved("QBT-002")
    brief = FactGuard(product).allowed_fact_brief()
    assert "item.taobao.com" not in brief, "提示词里不应该出现链接"
    assert "价格" in brief
