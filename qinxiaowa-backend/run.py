"""本地启动脚本。

用法：
    python run.py                # 按 .env 配置启动（默认 0.0.0.0:8000）
    python run.py --reload       # 开发模式，改代码自动重启
    python run.py --port 9000    # 临时换端口
    python run.py --host-only    # 只监听 127.0.0.1（仅本机访问）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证从任意工作目录执行都能 import 到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()

    parser = argparse.ArgumentParser(description="秦小娲的秦巴茶舍 · 后端服务")
    parser.add_argument("--host", default=settings.app_host, help="监听地址")
    parser.add_argument("--port", type=int, default=settings.app_port, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式自动重载")
    parser.add_argument("--host-only", action="store_true", help="只监听 127.0.0.1")
    args = parser.parse_args()

    host = "127.0.0.1" if args.host_only else args.host

    print("=" * 62)
    print("  秦小娲的秦巴茶舍 · 后端服务")
    print(f"  接口文档 : http://127.0.0.1:{args.port}/docs")
    print(f"  健康自检 : http://127.0.0.1:{args.port}/api/health")
    print(f"  资料库   : {settings.catalog_backend} -> {settings.catalog_path}")
    print(f"  大模型   : {'已启用（仅改写对白）' if settings.llm_ready else '未启用（模板对白，功能完整）'}")
    print(f"  外链白名单: {sorted(settings.allowed_host_set) or '未配置（按未接入处理）'}")
    print("=" * 62)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
