"""命令行端的演示 / 自检脚本。

不启动 HTTP 服务，直接调用服务层跑完分工方案第 05 节的验收路径，
方便在演示前 10 秒确认"整条链路没问题"。

用法：
    python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.deps import Container  # noqa: E402
from app.models.api_schemas import RecommendRequest  # noqa: E402
from app.services.fact_guard import FactGuard  # noqa: E402

LINE = "-" * 72


def title(text: str) -> None:
    print(f"\n{LINE}\n{text}\n{LINE}")


def show(response) -> None:
    if response.recommendation is None:
        print(f"  【结果】{response.result.value}：{response.message}")
        return
    rec = response.recommendation
    print(f"  【结果】{response.result.value}  {response.message}")
    print(f"  商品    : {rec.name}（{rec.product_id}）")
    specs_text = "；".join("{0}={1}".format(item["label"], item["value"]) for item in rec.specs)
    print(f"  价格    : {rec.price.get('display')}")
    print(f"  规格    : {specs_text or '（资料未提供）'}")
    print(f"  来源状态: {rec.source_status['review_status_label']} / {rec.source_status['material_source']}")
    print(f"  购买出口: {rec.purchase_mode}"
          + (f" -> {rec.shop_link['url']}" if rec.shop_link else "（未接入，仅展示资料，无假下单）"))
    print(f"  对白    : {rec.dialogue}")
    print(f"  理由    : {rec.reason}")
    if rec.missing_facts:
        print(f"  资料缺失: {'；'.join(rec.missing_facts)}")
    print(f"  [诊断] 对白来源={response.meta.dialogue_source.value} "
          f"降级={response.meta.degraded} 耗时={response.meta.elapsed_ms}ms 得分={rec.match_score}")


async def main() -> int:
    container = Container()
    stats = container.catalog.stats()

    title("环境自检")
    print(f"  资料库  : {stats['backend']} -> {stats['path']}")
    print(f"  商品数量: 共 {stats['total']} 款，已审核 {stats['approved']} 款，待审核 {stats['pending']} 款")
    print(f"  大模型  : {'已启用（仅改写对白）' if container.settings.llm_ready else '未启用（内置模板，功能完整）'}")
    print(f"  外链白名单: {container.link_guard.whitelist or '未配置（全部按未接入处理）'}")
    if stats["degraded"]:
        print(f"  [警告] {stats['degraded_reason']}")

    service = container.teahouse
    failures: list[str] = []

    title("案例一 · 自用（扫码入店 → 选自用 → 推荐一款）")
    r1 = await service.recommend(
        RecommendRequest(scene="self", budget=150, preference=["light", "beginner"], session_id="smoke-1")
    )
    show(r1)
    if r1.recommendation is None:
        failures.append("案例一未返回推荐")
    else:
        verdict = FactGuard(container.catalog.get_approved(r1.recommendation.product_id)).validate(
            r1.recommendation.dialogue
        )
        if not verdict.ok:
            failures.append(f"案例一对白未过护栏：{verdict.reason()}")

    title("案例二 · 礼赠长辈（要礼盒 → 换一款 → 查看店铺）")
    r2 = await service.recommend(
        RecommendRequest(
            scene="gift", recipient="elder", budget="100-300", preference=["gift_ready"], session_id="smoke-2"
        )
    )
    show(r2)

    print("\n  —— 点击「换一款」 ——")
    r2b = await service.recommend(
        RecommendRequest(scene="gift", recipient="elder", budget=300, session_id="smoke-2"), is_switch=True
    )
    show(r2b)
    if r2.recommendation and r2b.recommendation and r2.recommendation.product_id == r2b.recommendation.product_id:
        failures.append("换一款返回了同一款商品")

    print("\n  —— 再换一款（应明确提示暂无其他匹配）——")
    r2c = await service.recommend(RecommendRequest(scene="gift", budget=300, session_id="smoke-2"), is_switch=True)
    show(r2c)
    if r2c.result.value != "no_other_match":
        failures.append("无其他匹配时未返回明确提示")

    title("案例三 · 了解安康（文化与产地为主，无依据处明确说明）")
    r3 = await service.recommend(
        RecommendRequest(scene="ankang_intro", preference="想了解一下安康本地的茶", session_id="smoke-3")
    )
    show(r3)
    if r3.recommendation:
        card = r3.recommendation.culture_card
        print(f"  文化卡  : {card['title']}")
        print(f"  产地    : {card['origin'] or '（资料未提供，已明确说明）'}")
        print(f"  说明    : {card['verification_note']}")

    title("异常与边界（HTTP 层会统一返回 {error: {...}}）")

    from pydantic import ValidationError

    try:
        RecommendRequest(scene="gift", budget={"min": 300, "max": 100})
        print("  预算下限>上限：未被拦截（异常）")
        failures.append("非法预算未在入参校验阶段被拦截")
    except ValidationError:
        print("  预算下限>上限 -> INVALID_INPUT（HTTP 422，retryable=true）")

    try:
        RecommendRequest(scene="不存在的场景")
        print("  非法场景：未被拦截（异常）")
        failures.append("非法场景未在入参校验阶段被拦截")
    except ValidationError:
        print("  非法场景     -> INVALID_INPUT（HTTP 422，retryable=true）")

    missing = await service.recommend(RecommendRequest(scene="self", excluded_product_id="QBT-999"))
    print(f"  排除不存在的商品：{missing.result.value} -> "
          f"{missing.recommendation.name if missing.recommendation else '无'}")

    unseen = await service.recommend(RecommendRequest(scene="self", excluded_product_id="QBT-002"))
    print(f"  指定排除 QBT-002：{unseen.recommendation.product_id if unseen.recommendation else '无'}")

    unknown = await service.recommend(RecommendRequest(scene="self", preference=["会飞的味道"]))
    print(f"  无法识别的偏好：{unknown.intent.unknown_preferences}（原样回传，不猜测）")

    print(f"  未接入外链说明  ：{unknown.recommendation.shop_link_note or '无'}")
    print(f"  过程备注        ：{unknown.meta.notes}")

    title("总结")
    if failures:
        for item in failures:
            print(f"  [不通过] {item}")
        return 1
    print("  全部检查通过，可以开始演示。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
