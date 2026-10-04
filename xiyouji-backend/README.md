# 硒游记后端

FastAPI backend for the React frontend to be integrated later.

## 当前能力

- 混合知识库：结构化事实库 + 关键词检索知识库
- 七大场景、三关和三枚印章数据
- 商品目录、商品证据与官网购买链接接口
- 用户心愿解析与推荐接口
- 豆包/OpenAI-compatible API 可选接入
- 模型失败时自动切换预设推荐
- 疗效、夸大补硒和无依据事实的合规过滤
- CORS、请求长度限制和固定 JSON 响应结构

当前只做后端，不包含 React 页面、真实支付、用户账号和订单系统。
商品数据是演示结构，真实商品上线前必须替换为已授权、已核验的数据。

## 启动

```bash
cd C:/Users/13917/xiyouji-backend
uv sync
uv run uvicorn xiyouji.main:app --reload --port 58124
```

打开 `http://127.0.0.1:58124/docs` 查看接口。

可选环境变量：

- `LLM_BASE_URL`：默认 `https://api.openai-next.com/v1`
- `LLM_MODEL`：默认 `gpt-6-sol`
- `OPENAI_NEXT_API_KEY`：配置后启用模型推荐；未配置时使用预设降级
- `CORS_ORIGINS`：逗号分隔的前端来源，默认允许 localhost 常用端口

## React 对接接口

- `GET /api/health`
- `GET /api/scenes`
- `GET /api/stages`
- `GET /api/catalog?scene=water`
- `GET /api/catalog/{product_id}/evidence`
- `POST /api/chat`
- `POST /api/passport-copy`
