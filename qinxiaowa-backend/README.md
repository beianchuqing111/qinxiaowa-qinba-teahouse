# 秦小娲的秦巴茶舍 · 后端服务

> 黑客松企业赛道 · 首期最小可演示方案 · 后端部分
> 依据《秦小娲的秦巴茶舍_前后端分工》（讨论稿 V1.0，2026-10-02）与《技术架构图》实现

**技术栈**：Python + FastAPI · HTTPS/JSON · JSON 或 SQLite 资料库 · 可选大模型接口（仅改写对白）

---

## 一、这个仓库负责什么

按分工方案，前端负责**茶舍体验、角色呈现、操作反馈**；本仓库只做后端，边界如下：

| 分工方案要求 | 代码位置 |
|---|---|
| 提供 HTTPS/JSON 接口，校验场景、预算、偏好等输入 | `app/models/api_schemas.py`、`app/services/intent.py` |
| 识别送礼对象、预算和偏好 | `app/services/intent.py` |
| 仅在已录入、已审核商品内筛选 | `app/data/repository.py`、`app/services/recommender.py` |
| 返回单款推荐及理由 | `app/services/recommender.py`、`app/services/dialogue.py` |
| 「换一款」避开当前商品 | `app/services/session.py`、`app/api/routes/recommend.py` |
| 保存两款产品及文化卡、来源、审核状态、店铺链接 | `app/data/products.seed.json` |
| 从资料字段读取图片、规格、价格与产地；缺依据就明确说明 | `app/services/teahouse.py`（`missing_facts` / `origin_verified`） |
| 可接大模型生成简短对白，但不得编造产地、检测、价格或链接 | `app/services/llm.py` + `app/services/fact_guard.py` |
| 校验外链目标，控制异常、超时与可演示兜底 | `app/core/security.py`、`app/core/errors.py`、`app/data/repository.py` |

**不做**：页面与立绘、动画、语音识别与合成、口型驱动、多房间。这些是前端或第二阶段的事。

---

## 二、30 秒跑起来

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 启动（无需任何配置文件，默认读 JSON 资料库、大模型关闭）
python run.py

# 3. 打开接口文档
#    http://127.0.0.1:8000/docs
```

演示前建议先跑一次自检，它会直接把三个案例走一遍并检查对白是否合规：

```bash
python scripts/smoke_test.py
```

跑测试（54 项，含事实护栏、外链安全、降级兜底）：

```bash
pip install -r requirements-dev.txt
pytest
```

---

## 三、接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康与配置自检（资料库、大模型、外链白名单） |
| GET | `/api/health/detail` | 详细自检，含资料库路径与会话数 |
| GET | `/api/products` | 已审核商品列表（默认不返回待审核商品） |
| GET | `/api/products/{id}` | 单款详情：价格、规格、文化卡、来源状态、购买出口 |
| GET | `/api/scenes` | 场景 / 对象 / 偏好选项 + **3 个可重复演示用例** |
| POST | `/api/recommend` | 首次推荐 |
| POST | `/api/recommend/another` | 换一款（避开已看过的商品） |
| POST | `/api/recommend/greeting` | 迎宾态对白（不含商品事实） |
| GET | `/api/outbound/{id}` | 获取经白名单校验的店铺链接 |

完整字段说明见 [`docs/API.md`](docs/API.md)。

### 请求示例

```bash
curl -X POST http://127.0.0.1:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "scene": "gift",
    "recipient": "elder",
    "budget": "100-300",
    "preference": ["gift_ready"],
    "session_id": "demo-gift"
  }'
```

`scene` 取 `self`（自用）/ `gift`（礼赠）/ `ankang_intro`（了解安康）；
`budget` 支持 `200`、`"100-300"`、`{"min":100,"max":300}` 三种写法。

### 响应要点

```jsonc
{
  "result": "ok",                     // ok / no_match / no_other_match
  "message": "为您推荐「安康富硒红茶礼盒」",
  "intent": { "scene_label": "礼赠", "recipient_label": "长辈",
              "budget_display": "100-300 元", "preference_labels": ["礼盒装"] },
  "recommendation": {
    "product_id": "QBT-002",
    "name": "安康富硒红茶礼盒",
    "price": { "amount_cents": 26800, "display": "¥268 / 盒", "verified": true },
    "specs": [ { "label": "净含量", "value": "200g（100g × 2 罐）" } ],
    "dialogue": "……两三句简短对白……",
    "reason": "按「礼赠」为长辈筛选……",
    "culture_card": { "title": "…", "origin": null, "origin_verified": false },
    "source_status": { "review_status": "approved", "material_source": "…" },
    "shop_link": null,                 // 未接入时为 null
    "purchase_mode": "display_only",   // external_link / display_only
    "shop_link_note": "尚未配置店铺域名白名单，按未接入处理，只展示资料"
  },
  "meta": { "dialogue_source": "template", "degraded": false, "notes": [] }
}
```

前端渲染规则：`shop_link` 为 `null` 或 `purchase_mode = display_only` 时，**不得出现任何下单按钮**。

---

## 四、三条硬约束是怎么落地的

### 1. 只在已审核商品里推荐

`review_status` 不是 `approved` 的商品，在 `CatalogRepository` 层就被过滤掉，
连 `/api/products/{id}` 也按"不存在"处理（404），不会泄露未核验资料。
种子数据里的 `QBT-003` 就是用来验证这条的：它对任何接口都不可见。

### 2. 缺依据就明确说明，绝不编造

商品资料里每个可能被访客看到的事实字段都带 `verified` 标记：

- `price.verified = false` → 不展示金额，只显示"价格待核验"
- `culture_card.origin_verified = false` → 产地返回 `null`，附一句说明
- `missing_facts` 列出所有资料缺失项，会直接出现在对白与推荐理由里

例：`QBT-002` 的产地明细未提供，对白里就会说
"有一点先说明：具体茶园产地明细未提供，不指定具体乡镇。"

### 3. 大模型只允许改写措辞

开启大模型（`LLM_ENABLED=true`）后，流程是：

```
模板对白（100% 由已核验字段拼装）
        ↓
   交给大模型润色（提示词里只给允许事实，禁止写数字）
        ↓
   FactGuard 事实护栏校验
        ↓
   通过 → 采用；不通过或超时 → 丢弃，回退模板
```

`FactGuard` 会拦截三类幻觉，任何一条命中就整段作废：

- **数字幻觉**：出现资料库里没有的数字（含量、克重、年份、检测值）
- **资质/功效幻觉**：检测合格、有机认证、获奖、降压排毒、绝对化用语
- **产地幻觉**：出现资料未记录的具体县/镇/乡/村

同时允许"明确的否定表述"——"这款暂时没有提供检测报告"是**合规**的，
因为它没有创造事实，而是在说明资料缺失。

---

## 五、外部依赖出问题时怎么办

| 故障 | 行为 |
|---|---|
| 大模型超时 / 报错 / 返回垃圾 | 自动回退内置模板对白，`meta.degraded=true` 说明原因，功能不受影响 |
| 大模型试图编造事实 | 护栏拦截，回退模板，`meta.dialogue_source=llm_rejected` |
| 资料库文件被写坏 | 使用"最近一次成功加载"的内存快照继续服务，`meta.degraded=true` |
| 配了 SQLite 但库还没生成 | 自动回退到种子 JSON，并在日志中提示 |
| 外链不在白名单 / 用的是 http | 按"未接入"处理，返回 `shop_link=null`，不给任何跳转入口 |
| 换一款但已无其他商品 | 返回 `no_other_match` + "暂无其他匹配"，`recommendation=null` |
| 入参非法 | 统一返回 `422 {error: {code, message, retryable, detail}}` |

所有失败都带 `retryable` 标记，前端据此展示"重试 / 退出"。

---

## 六、配置

复制 `.env.example` 为 `.env` 后按需修改；**不配置也能完整演示**。

```bash
CATALOG_BACKEND=json              # json | sqlite
CORS_ALLOW_ORIGINS=http://localhost:5173

# 接入真实店铺后才填，填了才会出现跳转按钮
SHOP_LINK_ALLOWED_HOSTS=item.taobao.com,detail.tmall.com

# 可选大模型：不开也完全能用
LLM_ENABLED=false
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=6
```

切换到 SQLite：

```bash
python scripts/seed_sqlite.py
# 然后把 .env 里的 CATALOG_BACKEND 改成 sqlite
```

---

## 七、给前端同学的对接说明

1. 启动后端 `python run.py`，默认 `http://127.0.0.1:8000`。
2. 调 `GET /api/scenes` 拿场景 / 对象 / 偏好的选项中英文标签与**3 个演示用例**，
   不要去前端硬编码中文映射。
3. 首次推荐调 `POST /api/recommend`，把 `session_id` 带上（随便一个 uuid 即可）。
4. "换一款"调 `POST /api/recommend/another`，请求体跟上一次完全相同即可——
   后端会从会话里自动排除已经看过的商品，不会重复。
5. **价格、规格、图片、产地、文化卡一律用接口返回值渲染**，不要在前端写死。
6. `shop_link` 为 `null` 时，只展示资料，不要拼"去下单"按钮。
7. `meta.degraded = true` 时可以在调试面板显示 `meta.degraded_reason`，
   但用户侧不用提示——此时返回的内容依然是合规可展示的。

跨域已开，默认允许 `http://localhost:5173`。前端开发端口不同的话，
改 `.env` 里的 `CORS_ALLOW_ORIGINS`。

---

## 八、目录结构

```
qinba-teahouse-backend/
├── app/
│   ├── main.py                 # 应用入口：装配路由、异常处理、CORS
│   ├── core/
│   │   ├── config.py           # 全部可调参数（支持 .env 覆盖）
│   │   ├── errors.py           # 统一错误码与 {error:{...}} 响应
│   │   ├── logging.py          # 日志格式
│   │   └── security.py         # 外链白名单校验（购买出口安全）
│   ├── models/
│   │   ├── enums.py            # 场景 / 对象 / 偏好 / 审核状态 + 中文标签表
│   │   ├── product.py          # 商品与文化卡领域模型（含 verified 标记）
│   │   └── api_schemas.py      # 请求 / 响应契约
│   ├── data/
│   │   ├── products.seed.json  # 首期两款商品 + 一款待审核示例
│   │   └── repository.py       # JSON / SQLite 读取 + 缓存 + 降级兜底
│   ├── services/
│   │   ├── intent.py           # 需求识别：预算、偏好、送礼对象归一化
│   │   ├── recommender.py      # 受约束推荐打分与放宽策略
│   │   ├── dialogue.py         # 对白与推荐理由（模板 + 大模型润色）
│   │   ├── fact_guard.py       # 事实护栏：数字 / 资质 / 功效 / 产地
│   │   ├── llm.py              # 可选大模型客户端（超时即降级）
│   │   ├── session.py          # 会话状态：记住已看过的商品
│   │   └── teahouse.py         # 编排层：串起整条链路并组装响应
│   └── api/
│       ├── deps.py             # 依赖装配
│       └── routes/             # health / catalog / recommend / outbound
├── scripts/
│   ├── smoke_test.py           # 命令行跑通三个演示案例
│   └── seed_sqlite.py          # 种子 JSON 导入 SQLite
├── tests/                      # 54 项测试
├── docs/
│   ├── API.md                  # 接口详细字段说明（前端交接用）
│   └── ARCHITECTURE.md         # 分层设计与数据流
├── .env.example
├── Dockerfile
├── requirements.txt
└── run.py
```

---

## 九、演示前检查清单

- [ ] `python scripts/smoke_test.py` 输出"全部检查通过"
- [ ] `GET /api/health` 的 `approved_product_count` ≥ 2
- [ ] 三个案例都能走通：自用 / 礼赠 / 了解安康
- [ ] 「换一款」换到不同商品，再换会提示"暂无其他匹配"
- [ ] 未接入商品的页面上没有下单按钮
- [ ] 手机连同一局域网，用 `http://<电脑IP>:8000/docs` 能打开

> 商品与文化素材需由内容负责人提供并核验后再录入。
> 当前 `app/data/products.seed.json` 中的示例值仅供前后端联调，正式演示前请替换为核验后的真实数据。
