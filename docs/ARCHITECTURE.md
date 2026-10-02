# 后端分层设计与数据流

对应《秦小娲的秦巴茶舍 · 技术架构图》中"服务与推理"一侧的四个方框：
**API / 编排层** → **受约束推荐** → **商品 / 文化资料库** → **大模型接口（可选接入）**
以及出口处的 **购买出口 / 资料展示**。

---

## 1. 请求全链路

```
前端 POST /api/recommend
        │
        ▼
┌───────────────────────────────────────────────┐
│ api/routes/recommend.py   接口层               │
│  · 请求体 Pydantic 校验（scene/recipient/…）    │
└──────────────────┬────────────────────────────┘
                   ▼
┌───────────────────────────────────────────────┐
│ services/intent.py   需求识别                  │
│  · 中文口语 → 结构化约束                        │
│  · 预算 "100-300" / "两百左右" → min/max        │
│  · "想送长辈一个体面的礼盒" → elder + gift_ready │
│  · 识别不了的词原样放进 unknown_preferences      │
└──────────────────┬────────────────────────────┘
                   ▼
┌───────────────────────────────────────────────┐
│ data/repository.py   资料库（JSON / SQLite）    │
│  · 只取 review_status = approved 的商品         │
│  · 缓存 + mtime 判断，读盘失败用上次成功快照      │
└──────────────────┬────────────────────────────┘
                   ▼
┌───────────────────────────────────────────────┐
│ services/recommender.py   受约束推荐            │
│  约束层级：                                     │
│   ① 场景 + 预算 严格命中                        │
│   ② 放宽预算（保留场景），取最接近预算的一款       │
│   ③ 放宽场景（资料未打标签时兜底），并说明原因      │
│  打分：场景 40 / 对象 25 / 预算 25 / 偏好 8×N     │
│  换一款：排除集合（显式 ID ∪ 会话已看过的商品）     │
└──────────────────┬────────────────────────────┘
                   ▼
┌───────────────────────────────────────────────┐
│ services/dialogue.py   对白与理由               │
│  · build_template()：100% 用已核验字段拼装       │
│  · compose()：可选交给大模型润色                  │
└──────────────────┬────────────────────────────┘
                   ▼
┌───────────────────────────────────────────────┐
│ services/llm.py（可选）→ services/fact_guard.py │
│  大模型输出 → 事实护栏 → 通过则采用，否则回退模板   │
└──────────────────┬────────────────────────────┘
                   ▼
┌───────────────────────────────────────────────┐
│ core/security.py   外链校验 + services/teahouse │
│  白名单 https 才下发 shop_link，否则 display_only│
│  汇总成 RecommendResponse                       │
└───────────────────────────────────────────────┘
```

---

## 2. 为什么这样分层

| 层 | 只做一件事 | 换掉它的成本 |
|---|---|---|
| `api/routes` | HTTP 语义：状态码、路径、请求体校验 | 改路径不影响业务 |
| `services/intent` | 把访客的话变成约束，**不查商品** | 换识别模型（规则 → LLM）只改这里 |
| `data/repository` | 存储与审核过滤，**不懂业务** | JSON → SQLite → Postgres 只改这里 |
| `services/recommender` | 纯函数式打分与放宽策略 | 可单测、可调权重 |
| `services/dialogue` | 组织措辞，**不产生事实** | 换文风只改这里 |
| `services/fact_guard` | 独立的安全边界 | 可单独针对新风险加规则 |
| `services/teahouse` | 编排与响应组装 | 唯一知道全流程的地方 |

关键点：**事实护栏与推荐打分都拿到独立的 `Product` 对象**，
它们不共享状态，可以分别测试与替换。

---

## 3. 事实与内容安全的四个机制

### 3.1 字段级核验标记（数据层）

`Product` 里每个可能被访客看到的字段都带 `verified`：

```jsonc
"price":   { "amount_cents": 12800, "verified": true },
"specs":   [ { "label": "净含量", "value": "100g", "verified": true } ],
"culture_card": { "origin": null, "origin_verified": false }
```

`fact_digest()` 只导出 `verified = true` 的字段，未核验的字段对外是 `null`，
配套 `missing_facts` 显式列出缺失项。

### 3.2 审核状态过滤（存储层）

`CatalogRepository.get_approved()` 与 `.approved` 属性是唯一的读取出口。
`pending_review` / `rejected` 的商品：

- 不进推荐池
- 不出现在 `/api/products`
- `GET /api/products/{id}` 返回 404

### 3.3 事实护栏（服务层）

`FactGuard(product).validate(text)` 以该商品的可核验事实为白名单，拦截：

| 风险 | 检测方式 | 例子 |
|---|---|---|
| 数字幻觉 | 文本里每个数字都必须在资料库中出现过 | "含硒 42 毫克" → 拦截 |
| 年份幻觉 | `19xx/20xx 年` 必须在资料库中出现过 | "从 1893 年开始种植" → 拦截 |
| 资质幻觉 | 词表命中且资料库未提供 | "通过了有机认证" → 拦截 |
| 功效违规 | 医疗功效词表 | "可以降血压" → 拦截 |
| 绝对化用语 | "最好/第一/全网最低" | → 拦截 |
| 成分含量幻觉 | 资料未提供含量 | "硒含量为 0.3" → 拦截 |
| 产地幻觉 | 地名变体与资料库比对 | "采自平利县八仙镇" → 拦截 |

**允许否定表述**：判定词表命中时会往左看 12 个字，若出现"未/没有/暂无"等否定词，
则放行——因为"这款没有提供检测报告"没有创造事实，反而是在说明资料缺失。

### 3.4 外链白名单（安全层）

`ShopLinkGuard.evaluate()` 必须全部满足才放行：

1. 协议是 `https`
2. 主机在 `SHOP_LINK_ALLOWED_HOSTS` 内（支持子域）
3. 不是 IP 直连
4. URL 不带账号密码
5. 不含 `url=` / `redirect=` 这类跳板参数

白名单为空 = 全部按"未接入"处理，前端拿到的 `shop_link` 恒为 `null`。

---

## 4. 降级与兜底策略

设计目标：**任何一个外部依赖挂掉，演示闭环都不能断。**

| 依赖 | 失败表现 | 兜底行为 | 对外可见性 |
|---|---|---|---|
| 大模型 | 超时 / 4xx / 空响应 | 回退模板对白 | `meta.degraded=true`，内容正常 |
| 大模型 | 编造事实 | 护栏拦截，回退模板 | `meta.dialogue_source=llm_rejected` |
| 资料库文件 | 不存在 / 损坏 | 用上次成功加载的内存快照 | `meta.degraded=true` |
| SQLite | 库文件未生成 | 自动回退种子 JSON | `meta.degraded=true` |
| 外链 | 不在白名单 | `purchase_mode=display_only` | `shop_link=null` + 说明文案 |
| 推荐 | 严格条件无解 | 逐层放宽并说明原因 | `meta.relaxed=true` |
| 推荐 | 换一款已无商品 | `result=no_other_match` | 明确提示"暂无其他匹配" |
| 会话 | 进程重启丢失 | 前端重发请求即恢复 | 仅影响"换一款"的去重 |

`meta.notes` 记录的是**预期状态**（未接入外链、放宽了预算），
`meta.degraded` 记录的是**真实降级**（模板兜底、资料库快照）。两者语义分开，
避免前端把正常业务状态当成故障提示。

---

## 5. 会话状态

`SessionStore` 是进程内 LRU + TTL 的轻量实现，只存两样东西：

```python
SessionState:
    current_product_id   # 桌上当前这款
    seen_product_ids     # 本次会话已经看过的全部商品（保证换一款不重复）
```

`session_ttl_seconds` 默认 1800 秒，`session_max_entries` 默认 5000。
若后续要多实例部署，把 `SessionStore` 换成 Redis 实现即可，接口不变：

```python
get(session_id) / touch(session_id, current_product_id=…) / clear(session_id)
```

---

## 6. 数据模型速览

```
Product
├── id / name / subtitle / category
├── review_status            approved | pending_review | rejected
├── price        PriceInfo   amount_cents(int) / unit / verified
├── specs        SpecItem[]  label / value / verified
├── images       string[]    图片地址（前端直接用）
├── culture_card CultureCard title / origin(+verified) / paragraphs / facts / sources
├── source       SourceInfo  material_source / reviewer / reviewed_at / notes
├── shop_link    ShopLink    platform / url / enabled
├── tags         MatchTags   scenes[] / recipients[] / preferences[]
├── missing_facts string[]   资料缺失项（只允许"说明缺失"，不允许编造）
└── sibling_ids  string[]    同系列可换款提示
```

金额一律用整数分存储（`amount_cents`），避免浮点误差；`display` 由后端生成，
防止前端各算各的。

---

## 7. 扩展点

| 想做的事 | 改哪里 |
|---|---|
| 商品从 2 款加到 N 款 | 只改 `app/data/products.seed.json`，代码无需变动 |
| 换成抖音/拼多多店铺 | 改种子数据的 `shop_link.url` + `.env` 的 `SHOP_LINK_ALLOWED_HOSTS` |
| 加后台录入界面 | 复用 `data/repository.py` 的 `SqliteCatalogSource.initialize()` |
| 换向量检索 | 新增 `data/vector_source.py` 实现同一套 `approved` 接口 |
| 第二阶段接 ASR/TTS | 与本仓库解耦，另起服务；本仓库的对白文本字段不变 |
| 多实例部署 | 把 `SessionStore` 换成 Redis 实现 |

---

## 8. 已知取舍

- **会话在内存里**：进程重启后"换一款"的去重历史会丢失。首期演示可接受，多实例需换 Redis。
- **推荐为规则打分**：2 款商品不值得引入向量检索；规则可解释、可回归测试，
  且分工方案明确"首期不必引入向量数据库"。
- **护栏基于词表 + 白名单**：对中文语义的覆盖不如模型判别全面，
  但它的优势是**确定性**——同一段文本的判定结果永远一致，适合比赛现场。
  后续可叠加一层模型判别，作为护栏的第二道。
- **外链只做静态校验**：不做实时连通性探测，避免演示现场因网络波动误判为不可用。
