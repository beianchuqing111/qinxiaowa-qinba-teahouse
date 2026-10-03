"""购买出口 / 资料展示。

对应分工方案："已接入：明示跳转淘宝等真实商品页；未接入：只展示资料，不伪装下单"。

前端拿到 allowed=false 时，只能渲染"该商品暂未接入线上店铺"，
不允许自己拼一个下单按钮。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Container, container_of
from app.models.api_schemas import OutboundLinkResponse

router = APIRouter(prefix="/outbound", tags=["购买出口"])


@router.get(
    "/{product_id}",
    response_model=OutboundLinkResponse,
    summary="获取可跳转的真实店铺链接（白名单校验后返回）",
)
def outbound_link(
    product_id: str,
    container: Container = Depends(container_of),
) -> OutboundLinkResponse:
    payload = container.teahouse.outbound_link(product_id)
    return OutboundLinkResponse(**payload)


@router.get("/{product_id}/check", summary="外链可用性快速自检（联调用）")
def outbound_check(product_id: str, container: Container = Depends(container_of)) -> dict:
    payload = container.teahouse.outbound_link(product_id)
    return {
        "product_id": payload["product_id"],
        "allowed": payload["allowed"],
        "purchase_mode": payload["purchase_mode"],
        "host": payload["host"],
        "whitelist": container.link_guard.whitelist,
        "message": payload["message"],
    }
