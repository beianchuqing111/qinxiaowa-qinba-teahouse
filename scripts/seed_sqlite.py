"""把种子 JSON 导入 SQLite 资料库。

用法：
    python scripts/seed_sqlite.py
    python scripts/seed_sqlite.py --source app/data/products.seed.json --target app/data/teahouse.db

之后把 .env 里的 CATALOG_BACKEND 改成 sqlite 即可切换到 SQLite。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import PROJECT_ROOT, get_settings  # noqa: E402
from app.data.repository import SqliteCatalogSource  # noqa: E402


def main() -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(description="秦巴茶舍 · 资料库导入 SQLite")
    parser.add_argument("--source", default=str(settings.resolve_path(settings.catalog_json_path)))
    parser.add_argument("--target", default=str(settings.resolve_path(settings.catalog_sqlite_path)))
    args = parser.parse_args()

    source = Path(args.source)
    target = Path(args.target)

    if not source.exists():
        print(f"[失败] 找不到种子文件：{source}")
        return 1

    with source.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    products = payload.get("products", payload) if isinstance(payload, dict) else payload
    if not isinstance(products, list) or not products:
        print("[失败] 种子文件里没有 products 数组")
        return 1

    count = SqliteCatalogSource.initialize(target, products)
    print(f"[完成] 已写入 {count} 条商品 -> {target}")
    print(f"[提示] 把 .env 中的 CATALOG_BACKEND 改为 sqlite 即可切换（当前项目根目录：{PROJECT_ROOT}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
