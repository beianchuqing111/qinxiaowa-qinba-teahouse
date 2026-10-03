"""会话状态。

对应架构图里的"会话状态"一格。用途只有一个：
记住访客当前桌上的商品，这样前端点"换一款"时即使不传商品 ID，
后端也能自动避开它，不会出现"换了还是同一款"。

实现为进程内 LRU + TTL 的轻量存储，足够首期演示。
若后续要多实例部署，把本类换成 Redis 实现即可，接口不变。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from app.core.config import Settings


@dataclass
class SessionState:
    session_id: str
    current_product_id: str | None = None
    # 本次会话已经推荐过的商品，按顺序累积。
    # 「换一款」会排除这里全部商品，保证不会来回重复同一款。
    seen_product_ids: list[str] = field(default_factory=list)
    last_request: dict = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self, settings: Settings) -> None:
        self.ttl = settings.session_ttl_seconds
        self.max_entries = settings.session_max_entries
        self._data: OrderedDict[str, SessionState] = OrderedDict()
        self._lock = threading.Lock()

    def _evict_expired(self, now: float) -> None:
        expired = [key for key, state in self._data.items() if now - state.updated_at > self.ttl]
        for key in expired:
            self._data.pop(key, None)

    def get(self, session_id: str | None) -> SessionState | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            self._evict_expired(now)
            state = self._data.get(session_id)
            if state is None:
                return None
            self._data.move_to_end(session_id)
            return state

    def touch(
        self,
        session_id: str | None,
        *,
        current_product_id: str | None = None,
        last_request: dict | None = None,
    ) -> SessionState | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            self._evict_expired(now)
            state = self._data.get(session_id) or SessionState(session_id=session_id)
            if current_product_id is not None:
                state.current_product_id = current_product_id
                if current_product_id not in state.seen_product_ids:
                    state.seen_product_ids.append(current_product_id)
            if last_request is not None:
                state.last_request = last_request
            state.updated_at = now
            self._data[session_id] = state
            self._data.move_to_end(session_id)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
            return state

    def clear(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        with self._lock:
            return self._data.pop(session_id, None) is not None

    def stats(self) -> dict:
        with self._lock:
            self._evict_expired(time.time())
            return {"active_sessions": len(self._data), "ttl_seconds": self.ttl}
