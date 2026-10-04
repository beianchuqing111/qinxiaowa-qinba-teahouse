企业赛道 - 安康导购数字人 - 秦巴象限

当前版本包含：

- 原有硒游记单页导览网站和数字人对话界面
- FastAPI 对话代理，API Key 仅从后端环境变量读取
- PostgreSQL 商品库
- 商品公开接口和商品详情接口
- 商品管理页面：新增、编辑、上下架、上传图片
- 72 件商品初始化导入能力
- 本机商品图片静态访问

## 目录

- `app.py`：FastAPI 后端、商品 API、图片上传和对话代理
- `admin.html`：商品管理页面
- `xiyouji-website/`：原有网站和素材
- `tests/`：后端测试
- `.env.example`：环境变量模板

## 本地配置

复制 `.env.example` 为 `.env`，填写本机配置：

```env
DEEPSEEK_API_KEY=your-deepseek-api-key
DATABASE_URL=postgresql://postgres:your-password@127.0.0.1:5432/xiyouji
ADMIN_TOKEN=replace-with-a-long-random-local-token
```

`.env` 不应提交到 GitHub。

## 安装依赖

```bash
uv sync
```

## 启动后端

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8001
```

后端地址：`http://127.0.0.1:8001`

## 启动前端

在另一个终端执行：

```bash
cd xiyouji-website
python -m http.server 8000 --bind 127.0.0.1
```

前台地址：`http://127.0.0.1:8000`

## 商品管理

打开：`http://127.0.0.1:8001/admin`

输入 `.env` 中的 `ADMIN_TOKEN` 后，可以：

- 导入原有 72 件商品
- 新增商品
- 编辑商品
- 上传 JPG、PNG、WebP 图片
- 上架或下架商品

公开商品接口：

- `GET /api/products`
- `GET /api/products/{id}`
- `GET /api/scenes`

## 测试

```bash
uv run pytest -q
```
