"""推荐接口。

POST /api/recommend          首次推荐
POST /api/recommend/another  换一款（避开上一款）
POST /api/recommend/greeting 迎宾态对白（不涉及商品事实）

约定与分工方案第 03 节一致：
  请求：scene, recipient, budget, preference, excluded_product_id
  返回：商品 ID、名称、图片、价格与规格、简短对白、推荐理由、
        文化卡、来源状态、店铺链接（若已接入）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.api.deps import Container, container_of
from app.models.api_schemas import (
    NormalizedIntent,
    RecommendRequest,
    RecommendResponse,
)

router = APIRouter(prefix="/recommend", tags=["推荐"])


@router.post("", response_model=RecommendResponse, summary="首次推荐：返回单款商品与理由")
async def recommend(
    payload: RecommendRequest,
    container: Container = Depends(container_of),
) -> RecommendResponse:
    return await container.teahouse.recommend(payload)


@router.post(
    "/another",
    response_model=RecommendResponse,
    summary="换一款：避开当前商品，无其他匹配时明确返回提示",
)
async def recommend_another(
    payload: RecommendRequest,
    container: Container = Depends(container_of),
) -> RecommendResponse:
    """换一款。

    排除项优先取请求里的 excluded_product_id；
    若前端没传，则自动使用会话里记录的当前商品。
    """
    return await container.teahouse.recommend(payload, is_switch=True)


@router.post("/greeting", summary="迎宾态对白（不引用任何商品事实）")
async def greeting(
    container: Container = Depends(container_of),
    payload: RecommendRequest | None = Body(default=None),
) -> dict:
    intent: NormalizedIntent | None = None
    if payload is not None:
        intent = container.intent.normalize(payload).intent
    return {
        "state": "greeting",
        "dialogue": container.dialogue.greeting(intent),
        "hint": "访客选择场景或直接输入需求后，调用 /api/recommend 进入推荐态",
    }
