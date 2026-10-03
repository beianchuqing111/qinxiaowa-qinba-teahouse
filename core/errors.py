"""统一错误模型与异常处理器。

对前端承诺：任何失败都返回同一种 JSON 结构，且带 retryable 标记，
前端据此展示"接口失败，可重试 / 可退出"的提示。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("qinba.errors")

# 直接写数字：starlette 新旧版本对 422 常量的命名不一致
# （HTTP_422_UNPROCESSABLE_ENTITY / HTTP_422_UNPROCESSABLE_CONTENT），
# 用字面量可以同时兼容两个版本且不触发弃用告警。
HTTP_422_UNPROCESSABLE = 422


class ErrorCode:
    """错误码常量：前端只需认识这几个值。"""

    INVALID_INPUT = "INVALID_INPUT"          # 入参校验失败
    NO_MATCH = "NO_MATCH"                    # 没有任何符合条件的商品
    NO_OTHER_MATCH = "NO_OTHER_MATCH"        # 换一款时已无其他符合条件的商品
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"  # 商品不存在或未过审
    LINK_NOT_ALLOWED = "LINK_NOT_ALLOWED"    # 外链未接入/不在白名单，不制造假下单
    CATALOG_UNAVAILABLE = "CATALOG_UNAVAILABLE"  # 资料库读取失败（已走兜底快照时不会出现）
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"    # 外部依赖超时（大模型等），已降级
    INTERNAL_ERROR = "INTERNAL_ERROR"        # 未预期异常


class AppError(Exception):
    """业务异常基类。"""

    code: str = ErrorCode.INTERNAL_ERROR
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "服务开小差了，请稍后再试"
    retryable: bool = True

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        http_status: int | None = None,
        detail: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.http_status = http_status or self.http_status
        self.detail = detail or {}
        if retryable is not None:
            self.retryable = retryable
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "detail": self.detail,
            }
        }


class InvalidInputError(AppError):
    code = ErrorCode.INVALID_INPUT
    http_status = HTTP_422_UNPROCESSABLE
    message = "提交的需求信息不完整或格式不正确"
    retryable = True


class NoMatchError(AppError):
    code = ErrorCode.NO_MATCH
    http_status = status.HTTP_200_OK
    message = "按当前需求暂时没有匹配的茶品，可以放宽预算或换一种偏好再试"
    retryable = True


class NoOtherMatchError(AppError):
    code = ErrorCode.NO_OTHER_MATCH
    http_status = status.HTTP_200_OK
    message = "暂无其他匹配"
    retryable = False


class ProductNotFoundError(AppError):
    code = ErrorCode.PRODUCT_NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND
    message = "没有找到这款商品，或该商品的资料尚未通过审核"
    retryable = False


class LinkNotAllowedError(AppError):
    code = ErrorCode.LINK_NOT_ALLOWED
    http_status = status.HTTP_409_CONFLICT
    message = "该商品暂未接入线上店铺，这里只展示已核验的资料"
    retryable = False


class CatalogUnavailableError(AppError):
    code = ErrorCode.CATALOG_UNAVAILABLE
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "商品资料暂时读取不到，请稍后重试"
    retryable = True


def register_exception_handlers(app: FastAPI) -> None:
    """把各类异常统一收敛成 {error: {...}} 结构。"""

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        logger.info("业务异常 code=%s message=%s", exc.code, exc.message)
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", []) if part != "body")
            fields.append({"field": location or "body", "reason": item.get("msg", "")})
        payload = AppError(
            "提交的需求信息不完整或格式不正确",
            code=ErrorCode.INVALID_INPUT,
            http_status=HTTP_422_UNPROCESSABLE,
            detail={"fields": fields},
        )
        return JSONResponse(status_code=payload.http_status, content=payload.to_payload())

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求无法完成"
        payload = AppError(message, code=f"HTTP_{exc.status_code}", http_status=exc.status_code)
        return JSONResponse(status_code=exc.status_code, content=payload.to_payload())

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常 path=%s", request.url.path)
        payload = AppError("服务开小差了，请稍后再试", code=ErrorCode.INTERNAL_ERROR)
        return JSONResponse(status_code=payload.http_status, content=payload.to_payload())
