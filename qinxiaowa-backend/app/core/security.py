"""外链安全校验（购买出口）。

对应分工方案："校验外链目标，并控制异常、超时与可演示兜底"、
"外链仅指向实际已接入商品，不制造虚假购买入口"。

规则（全部满足才允许跳转）：
  1. 协议必须是 https
  2. 主机必须在 SHOP_LINK_ALLOWED_HOSTS 白名单内（支持子域匹配）
  3. 禁止 javascript:/data:/file: 等危险协议，禁止带账号密码的 URL
  4. 禁止跳板型参数（url=/redirect=/target=），避免被当作开放重定向
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

from app.core.config import Settings

logger = logging.getLogger("qinba.linkguard")

DANGEROUS_SCHEMES = {"javascript", "data", "file", "vbscript", "blob", "about"}
REDIRECT_PARAM_HINTS = {"url", "redirect", "redirect_uri", "target", "jump", "goto", "to"}


@dataclass
class LinkDecision:
    allowed: bool
    url: str | None = None
    host: str | None = None
    reason: str | None = None


class ShopLinkGuard:
    """商铺外链白名单校验器。"""

    def __init__(self, settings: Settings) -> None:
        self.allowed_hosts = settings.allowed_host_set

    @property
    def whitelist(self) -> list[str]:
        return sorted(self.allowed_hosts)

    def _host_allowed(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        if not self.allowed_hosts:
            return False
        for allowed in self.allowed_hosts:
            if host == allowed or host.endswith("." + allowed):
                return True
        return False

    @staticmethod
    def _is_ip_host(host: str) -> bool:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return False
        return True

    def evaluate(self, url: str | None, *, platform: str = "店铺") -> LinkDecision:
        """判断某个外链是否可对外跳转。"""
        if not url:
            return LinkDecision(False, reason=f"该商品暂未接入线上{platform}链接")

        candidate = url.strip()
        parsed = urlparse(candidate)

        if parsed.scheme.lower() in DANGEROUS_SCHEMES:
            logger.warning("拦截危险协议外链：%s", parsed.scheme)
            return LinkDecision(False, reason="外链协议不受支持")

        if parsed.scheme.lower() != "https":
            return LinkDecision(False, reason="外链必须使用 https")

        host = (parsed.hostname or "").lower()
        if not host:
            return LinkDecision(False, reason="外链缺少有效域名")

        if parsed.username or parsed.password:
            return LinkDecision(False, reason="外链不得携带账号信息")

        if self._is_ip_host(host):
            return LinkDecision(False, reason="外链不得直接指向 IP 地址")

        if not self.allowed_hosts:
            return LinkDecision(
                False,
                host=host,
                reason="尚未配置店铺域名白名单，按未接入处理，只展示资料",
            )

        if not self._host_allowed(host):
            logger.warning("外链域名不在白名单：%s", host)
            return LinkDecision(False, host=host, reason=f"域名 {host} 不在已接入白名单内")

        for key, value in parse_qsl(parsed.query, keep_blank_values=False):
            if key.lower() in REDIRECT_PARAM_HINTS and value.startswith(("http://", "https://", "//")):
                logger.warning("外链疑似开放重定向：%s=%s", key, value)
                return LinkDecision(False, host=host, reason="外链包含可疑的跳转参数")

        return LinkDecision(True, url=candidate, host=host)

    def describe_disabled_reason(self, reason: str | None) -> str:
        return reason or "该商品暂未接入线上店铺"
