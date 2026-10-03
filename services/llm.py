"""可选大模型客户端。

定位（严格遵守架构图）："仅改写简短对白 · 不生成商品事实"。

因此这里：
  - 系统提示词强制模型只做措辞润色，输出长度受限
  - 任何超时 / 报错 / 非法响应都被吞掉并返回 None，由上层回退模板对白
  - 不在这一层做事实校验（交给 FactGuard），保持职责单一
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings

logger = logging.getLogger("qinba.llm")

SYSTEM_PROMPT = """你是"秦小娲"，安康秦巴茶舍里招呼客人的茶舍主理人，说话温和、简短、有分寸。

【硬性规则，违反即为失败】
1. 只能使用"允许事实"里出现过的信息，一个字都不能新增。
2. 绝对不要出现任何数字（价格、克重、含量、年份都不要写），价格与规格由页面单独展示。
3. 不要出现检测、认证、有机、获奖、功效、养生疗效等字眼，也不要评价"最好/第一/顶级"。
4. 不要编造具体到县、镇、乡、村的地名，除非"允许事实"里写了。
5. 资料没提供的内容，用"这个我这边暂时没有依据，就不乱说了"这类说明带过，或直接不提。
6. 不承诺物流、库存、售后与优惠。
7. 只输出两到三句话，总字数 60-110 字，中文口语，不要 emoji，不要 Markdown，不要换行。
8. 直接输出对白正文，不要任何前缀、解释或引号。"""


@dataclass
class LlmResult:
    text: str
    model: str


class LlmClient:
    """OpenAI 兼容的 Chat Completions 客户端（DeepSeek / 通义 / 自建均可）。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    # ---------- 生命周期 ----------
    async def startup(self) -> None:
        if not self.settings.llm_ready:
            return
        self._client = httpx.AsyncClient(
            base_url=self.settings.llm_base_url.rstrip("/"),
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
        )
        logger.info("大模型已启用 model=%s", self.settings.llm_model)

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------- 调用 ----------
    async def rewrite_dialogue(self, user_prompt: str) -> LlmResult | None:
        """改写对白。失败一律返回 None，绝不抛出异常影响主流程。"""
        if not self.settings.llm_ready or self._client is None:
            return None

        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 220,
            "stream": False,
        }

        attempts = max(1, self.settings.llm_max_retries + 1)
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post("/chat/completions", json=payload)
                if response.status_code >= 400:
                    logger.warning(
                        "大模型返回异常状态 attempt=%d status=%s body=%s",
                        attempt,
                        response.status_code,
                        response.text[:200],
                    )
                    continue
                data = response.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                text = self._clean(content)
                if not text:
                    logger.warning("大模型返回空内容 attempt=%d", attempt)
                    continue
                return LlmResult(text=text, model=self.settings.llm_model)
            except httpx.TimeoutException:
                logger.warning("大模型调用超时 attempt=%d（%.1fs）", attempt, self.settings.llm_timeout_seconds)
            except httpx.HTTPError as exc:
                logger.warning("大模型调用网络异常 attempt=%d error=%s", attempt, exc)
            except (KeyError, ValueError, IndexError) as exc:
                logger.warning("大模型响应无法解析 attempt=%d error=%s", attempt, exc)

        logger.info("大模型调用失败，已回退模板对白")
        return None

    def _clean(self, raw: str) -> str:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[-1] if "\n" in text else text
        for prefix in ("对白：", "对白:", "秦小娲：", "秦小娲:"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        text = text.replace("\n", " ").replace("\r", " ").strip().strip('"“”')
        limit = self.settings.llm_max_output_chars
        return text[:limit]
