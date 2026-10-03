"""商品 / 文化资料与前端选项。

对应分工方案："价格与规格不能只在前端硬编码"——所有展示字段都从这里取。
未过审商品不会出现在任何接口里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import Container, container_of
from app.models.api_schemas import (
    OptionGroupOut,
    ProductDetailResponse,
    ProductListResponse,
    ProductSummary,
)
from app.models.enums import PREFERENCE_LABELS, SCENE_LABELS
from app.services.teahouse import TeahouseService

router = APIRouter(prefix="/products", tags=["商品与文化资料"])


@router.get("", response_model=ProductListResponse, summary="已审核商品列表")
def list_products(
    container: Container = Depends(container_of),
    include_pending: bool = Query(
        default=False,
        description="内部核查用：是否包含待审核商品。正式对外必须保持 false",
    ),
) -> ProductListResponse:
    snapshot = container.catalog.load()
    pool = snapshot.products if include_pending else snapshot.approved
    service: TeahouseService = container.teahouse

    items = [
        ProductSummary(
            product_id=item.id,
            name=item.name,
            subtitle=item.subtitle,
            category=item.category,
            image_url=item.images[0] if item.images else None,
            price_display=(item.price.display if item.price.verified else "价格待核验"),
            price_verified=item.price.verified,
            review_status=item.review_status.value,
            purchase_mode=service.serialize_product(item)["purchase_mode"],
            scenes=[SCENE_LABELS.get(scene, scene) for scene in item.tags.scenes],
            preferences=[PREFERENCE_LABELS.get(pref, pref) for pref in item.tags.preferences],
        )
        for item in pool
    ]
    return ProductListResponse(total=len(items), items=items)


@router.get(
    "/{product_id}",
    response_model=ProductDetailResponse,
    summary="单款商品详情（含文化卡、来源状态与购买出口）",
)
def get_product(product_id: str, container: Container = Depends(container_of)) -> ProductDetailResponse:
    payload = container.teahouse.get_product(product_id)
    return ProductDetailResponse(**payload)


option_router = APIRouter(prefix="/scenes", tags=["前端选项"])


@option_router.get("", response_model=OptionGroupOut, summary="场景 / 对象 / 偏好选项与演示用例")
def get_options(container: Container = Depends(container_of)) -> OptionGroupOut:
    return OptionGroupOut(**container.teahouse.options())
