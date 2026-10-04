# 接口文档（前端交接用）

Base URL：`http://127.0.0.1:8000`，所有接口前缀 `/api`。
交互式文档：`GET /docs`（Swagger UI）、`GET /redoc`。

约定：请求与响应均为 `application/json; charset=utf-8`；金额统一用"分"为单位的整数存储，
同时下发 `display` 字段供直接渲染。

---

## 0. 错误结构

所有失败响应结构一致，前端只需按 `code` 分支处理：

```json
{
  "error": {
    "code": "INVALID_INPUT",
    "message": "提交的需求信息不完整或格式不正确",
    "retryable": true,
    "detail": { "fields": [ { "field": "scene", "reason": "Input should be 'self', 'gift' or 'ankang_intro'" } ] }
  }
}
```

| code | HTTP | 含义 | retryable |
|---|---|---|---|
| `INVALID_INPUT` | 422 | 入参校验失败 | true |
| `NO_MATCH` | 200（在正常响应里，`result=no_match`） | 没有任何匹配商品 | true |
| `NO_OTHER_MATCH` | 200（`result=no_other_match`） | 换一款时已无其他商品 | false |
| `PRODUCT_NOT_FOUND` | 404 | 商品不存在**或未过审** | false |
| `LINK_NOT_ALLOWED` | 409 | 外链不可用（未接入） | false |
| `CATALOG_UNAVAILABLE` | 503 | 商品资料读取不到（且无可用兜底） | true |
| `INTERNAL_ERROR` | 500 | 未预期异常 | true |

---

## 1. `GET /api/health`

服务与配置自检，演示前先看这个。

```json
{
  "status": "ok",
  "version": "1.0.0",
  "env": "dev",
  "catalog_backend": "json",
  "catalog_ready": true,
  "approved_product_count": 2,
  "llm_enabled": false,
  "llm_ready": false,
  "outbound_link_whitelist": []
}
```

`status` 为 `degraded` 表示当前没有可推荐的已审核商品。
`llm_ready=false` 只是说明对白走模板，**不影响功能**。

`GET /api/health/detail` 额外返回资料库路径、会话数、降级原因，用于现场排障。

---

## 2. `GET /api/products`

已审核商品列表。默认不返回 `pending_review` 的商品。

参数：`include_pending`（bool，默认 false，**仅内部核查用**）。

```json
{
  "total": 2,
  "items": [
    {
      "product_id": "QBT-001",
      "name": "紫阳富硒毛尖",
      "subtitle": "安康紫阳 · 明前绿茶 · 罐装 100g",
      "category": "绿茶",
      "image_url": "https://example-cdn.local/qbt-001/main.jpg",
      "price_display": "¥128 / 罐",
      "price_verified": true,
      "review_status": "approved",
      "purchase_mode": "display_only",
      "scenes": ["自用", "了解安康", "礼赠"],
      "preferences": ["绿茶", "清淡", "无添加", "易入口", "便携"]
    }
  ]
}
```

---

## 3. `GET /api/products/{product_id}`

单款详情：用于"看商品""看来历"。未过审或不存在的商品一律 404。

```json
{
  "product": {
    "product_id": "QBT-001",
    "name": "紫阳富硒毛尖",
    "subtitle": "安康紫阳 · 明前绿茶 · 罐装 100g",
    "category": "绿茶",
    "image_url": "https://example-cdn.local/qbt-001/main.jpg",
    "image_urls": ["…/main.jpg", "…/soup.jpg"],
    "price": {
      "amount_cents": 12800,
      "currency": "CNY",
      "unit": "罐",
      "verified": true,
      "display": "¥128 / 罐",
      "note": "示例价，正式演示前需按店铺实际售价核验"
    },
    "specs": [
      { "label": "净含量", "value": "100g" },
      { "label": "形态", "value": "散茶 · 罐装" }
    ],
    "culture_card": {
      "title": "紫阳茶 · 山与水的记忆",
      "origin": "陕西省安康市紫阳县",
      "origin_verified": true,
      "origin_note": null,
      "paragraphs": ["……", "……"],
      "facts": ["产自陕西省安康市紫阳县", "……"],
      "verification_note": "以上为产地文化描述，未包含具体成分含量与检测结论……",
      "sources": ["《秦小娲的秦巴茶舍_一页方案》讨论稿 V1.0", "……"]
    }
  },
  "source_status": {
    "review_status": "approved",
    "review_status_label": "已审核",
    "material_source": "内容负责人提供的商品图与产地文化说明（示例占位）",
    "reviewer": "待填写",
    "reviewed_at": "2026-10-02",
    "notes": "价格、图片、文化卡已录入；图片为占位地址"
  },
  "shop_link": null,
  "purchase_mode": "display_only",
  "missing_facts": [
    "检测报告与成分含量数据未提供，不对外展示",
    "线上店铺链接未接入，仅展示资料"
  ]
}
```

渲染规则：

- `price.verified = false` 时 `price.display` 为 `"价格待核验"`，**不要显示金额**。
- `culture_card.origin = null` 时展示 `origin_note` 的说明文案。
- `missing_facts` 建议以浅色小字展示，这正是"不编造"的体现。

---

## 4. `GET /api/scenes`

前端所有选项与演示用例的来源，避免两端硬编码中文。

```json
{
  "scenes": [
    { "value": "self", "label": "自用", "description": "想给自己找一款日常喝的茶" },
    { "value": "gift", "label": "礼赠", "description": "要带一份送人，需要体面又稳妥" },
    { "value": "ankang_intro", "label": "了解安康", "description": "想从一杯茶开始了解安康" }
  ],
  "recipients": [ { "value": "elder", "label": "长辈", "description": "" } ],
  "preferences": [ { "value": "gift_ready", "label": "礼盒装", "description": "需要有礼盒和手提袋" } ],
  "budget_hints": [
    { "label": "不限预算", "budget": null },
    { "label": "100 元以内", "budget": 100 },
    { "label": "100-300 元", "budget": { "min": 100, "max": 300 } },
    { "label": "300 元以上", "budget": 300 }
  ],
  "demo_cases": [
    { "id": "case-self",   "title": "案例一 · 自用",       "request": { "…": "直接 POST 到 /api/recommend" } },
    { "id": "case-gift",   "title": "案例二 · 礼赠长辈",   "request": { "…": "…" } },
    { "id": "case-ankang", "title": "案例三 · 了解安康",   "request": { "…": "…" }, "follow_up": { "switch": true } }
  ]
}
```

`demo_cases[].request` 可以原样作为 `/api/recommend` 的请求体，保证演示可重复。

---

## 5. `POST /api/recommend`（首次推荐）

### 请求

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `scene` | string | 是 | `self` / `gift` / `ankang_intro` |
| `recipient` | string \| null | 否 | `self` `elder` `parent` `friend` `client` `partner` `kid` |
| `budget` | number \| string \| object | 否 | `200` / `"100-300"` / `{"min":100,"max":300}` |
| `preference` | string[] \| string | 否 | 枚举值，或一段中文描述（如"想送长辈一个体面的礼盒"） |
| `excluded_product_id` | string | 否 | 要排除的商品 ID |
| `session_id` | string | 否 | 会话 ID，建议传（用于「换一款」自动排除） |
| `free_text` | string | 否 | 访客补充说明，仅做关键词提取 |

不允许未知字段（`extra="forbid"`，传了会返回 422）。

### 响应

```json
{
  "result": "ok",
  "message": "为您推荐「安康富硒红茶礼盒」",
  "intent": {
    "scene": "gift",
    "scene_label": "礼赠",
    "recipient": "elder",
    "recipient_label": "长辈",
    "budget_min_yuan": 100,
    "budget_max_yuan": 300,
    "budget_display": "100-300 元",
    "preferences": ["gift_ready"],
    "preference_labels": ["礼盒装"],
    "excluded_product_id": null,
    "unknown_preferences": []
  },
  "recommendation": {
    "product_id": "QBT-002",
    "name": "安康富硒红茶礼盒",
    "subtitle": "安康平利 · 双罐礼盒装 200g",
    "image_url": "https://example-cdn.local/qbt-002/main.jpg",
    "image_urls": ["…"],
    "price": { "amount_cents": 26800, "display": "¥268 / 盒", "unit": "盒", "verified": true },
    "specs": [ { "label": "净含量", "value": "200g（100g × 2 罐）" } ],
    "dialogue": "给长辈带茶，稳妥比新奇重要。……",
    "reason": "按「礼赠」为长辈筛选，预算 100-300 元，礼盒装，在已录入并审核通过的商品里匹配到这款。……",
    "reason_points": ["需求场景：礼赠", "适用对象：长辈", "价格：¥268 / 盒", "购买出口：未接入线上店铺，仅展示已核验资料"],
    "culture_card": { "…": "同 /api/products/{id}" },
    "source_status": { "…": "同 /api/products/{id}" },
    "shop_link": null,
    "purchase_mode": "display_only",
    "shop_link_note": "尚未配置店铺域名白名单，按未接入处理，只展示资料",
    "missing_facts": ["具体茶园产地明细未提供，不指定具体乡镇"],
    "match_score": 101
  },
  "alternatives_available": true,
  "meta": {
    "trace_id": "5f1c2a9b3d47",
    "dialogue_source": "template",
    "degraded": false,
    "degraded_reason": null,
    "notes": ["尚未配置店铺域名白名单，按未接入处理，只展示资料"],
    "relaxed": false,
    "relaxed_reason": null,
    "catalog_backend": "json",
    "candidate_count": 2,
    "eligible_count": 2,
    "elapsed_ms": 3
  }
}
```

### 无匹配时

```json
{
  "result": "no_match",
  "message": "按当前需求暂时没有匹配的茶品，可以把预算放宽一些，或者减少几个口味偏好。",
  "recommendation": null,
  "meta": { "…": "…" }
}
```

### 字段语义

- `result`：`ok` / `no_match` / `no_other_match`。**UI 分支只看这个字段**。
- `intent`：后端理解到的需求，可直接显示成"我理解为：礼赠 · 长辈 · 100-300 元 · 礼盒装"。
- `intent.unknown_preferences`：没识别出的词，原样回传。可提示"这部分我没太懂，已按其余条件推荐"。
- `meta.degraded`：`true` 表示走了降级路径（大模型不可用、资料库用了快照）。
  **此时内容依然合规可展示，用户侧无需提示**，调试面板显示 `degraded_reason` 即可。
- `meta.notes`：过程说明（如未接入外链、放宽了预算），不是故障。

---

## 6. `POST /api/recommend/another`（换一款）

请求体与 `/api/recommend` **完全相同**，建议原样重发上一次的请求体。

排除规则：

1. 请求里的 `excluded_product_id` 一定排除；
2. 带 `session_id` 时，本次会话中**已经推荐过的商品全部排除**（保证不来回重复）；
3. 不带 `session_id` 且显式传了 `excluded_product_id` 时，只排除该商品（允许前端自行控制来回切换）。

无其他商品时：

```json
{
  "result": "no_other_match",
  "message": "暂无其他匹配",
  "recommendation": null
}
```

命中时 `recommendation.reason` 中会带"已按您的要求避开上一款"。

---

## 7. `POST /api/recommend/greeting`

迎宾态对白，**不涉及任何商品事实**。请求体可省略。

```json
{
  "state": "greeting",
  "dialogue": "送人的东西，我尽量挑得稳妥些。这次是给长辈挑，还是您自己喝？",
  "hint": "访客选择场景或直接输入需求后，调用 /api/recommend 进入推荐态"
}
```

---

## 8. `GET /api/outbound/{product_id}`（购买出口）

只有通过白名单校验的 https 链接才会返回。

已接入：

```json
{
  "product_id": "QBT-002",
  "allowed": true,
  "purchase_mode": "external_link",
  "url": "https://item.taobao.com/item.htm?id=000000000000",
  "label": "前往淘宝查看同款",
  "host": "item.taobao.com",
  "message": "将跳转到淘宝的真实商品页，请以店铺页面信息为准"
}
```

未接入（**前端必须渲染成"仅展示资料"，不得出现下单按钮**）：

```json
{
  "product_id": "QBT-002",
  "allowed": false,
  "purchase_mode": "display_only",
  "url": null,
  "label": null,
  "host": null,
  "message": "尚未配置店铺域名白名单，按未接入处理，只展示资料"
}
```

`GET /api/outbound/{product_id}/check` 额外返回当前白名单，联调时用来确认配置是否生效。

---

## 9. 前端接入示例（TypeScript）

```ts
const BASE = "http://127.0.0.1:8000";
const sessionId = crypto.randomUUID();

type RecommendResult = "ok" | "no_match" | "no_other_match";

async function recommend(body: Record<string, unknown>) {
  const res = await fetch(`${BASE}/api/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, session_id: sessionId }),
  });
  if (!res.ok) {
    const { error } = await res.json();
    if (error.retryable) return { retryable: true, message: error.message };
    throw new Error(error.message);
  }
  return res.json();
}

async function switchOne(body: Record<string, unknown>) {
  const res = await fetch(`${BASE}/api/recommend/another`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, session_id: sessionId }),
  });
  return res.json();
}

// 渲染时：价格与规格一律用接口返回值
function renderPrice(price: { display: string | null; verified: boolean }) {
  return price.verified ? price.display : "价格待核验";
}

// 购买出口
function renderBuyButton(rec: { shop_link: unknown; purchase_mode: string }) {
  if (!rec.shop_link || rec.purchase_mode !== "external_link") {
    return null; // 未接入：只展示资料，不伪装下单
  }
  return rec.shop_link;
}
```

---

## 10. 联调注意事项

1. **价格与规格不能在前端硬编码**，一律读接口，这是分工方案里明确的要求。
2. `session_id` 建议用 `crypto.randomUUID()`；刷新页面后换新的即可，
   `smoke_test` 与 `demo_cases` 都用固定值以便重复演示。
3. 换一款建议直接重发上一次的请求体，后端会自动排除已看过的商品。
4. 后端默认允许 `http://localhost:5173` 跨域；端口不同请改 `.env` 的 `CORS_ALLOW_ORIGINS`。
5. 手机扫码访问时，Base URL 换成电脑局域网 IP，并确保后端以 `0.0.0.0` 监听（`python run.py` 默认如此）。
6. 响应是标准 UTF-8 JSON（`Content-Type: application/json`）。浏览器与 `fetch` / `axios` / `curl`
   都能正确解码中文；只有 Windows PowerShell 5.1 的 `Invoke-RestMethod` 在响应未带 charset 时会按
   Latin-1 解码导致中文乱码，换成 `curl` 或 `Invoke-WebRequest` 即可，这与服务端无关。
