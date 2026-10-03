from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import asyncpg
import httpx
import json
import os
import re
import secrets
import shutil

BASE = Path(__file__).resolve().parent
SITE = BASE / 'xiyouji-website'
UPLOADS = BASE / 'uploads' / 'products'
UPLOADS.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE / '.env')

page_text = (SITE / 'index.html').read_text(encoding='utf-8')
match = re.search(r'const GOODS = (.*?);\nconst SCENES', page_text, re.S)
GOODS = json.loads(match.group(1)) if match else []

SCENES = {
    'spring': '山泉瀑布', 'tea': '云雾茶园', 'field': '林下魔芋田',
    'kitchen': '村舍炊烟', 'store': '街边杂货铺', 'post': '江边驿站', 'xian': '安康好货'
}

pool = None

@asynccontextmanager
async def lifespan(app):
    global pool
    url = os.getenv('DATABASE_URL')
    if url:
        pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    price NUMERIC(12,2),
                    sales INTEGER,
                    scene_id TEXT NOT NULL,
                    official_url TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    image_path TEXT NOT NULL DEFAULT '',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            ''')
    yield
    if pool:
        await pool.close()
        pool = None

app = FastAPI(title='Xiyouji Local Chat and Catalog API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:8000', 'http://localhost:8000'], allow_methods=['GET','POST','PATCH'], allow_headers=['Content-Type','X-Admin-Token'])
app.mount('/uploads', StaticFiles(directory=UPLOADS), name='uploads')

class Message(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=12000)

class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=16)
    system_prompt: str = Field(min_length=1, max_length=50000)

class ProductInput(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    price: float | None = Field(default=None, ge=0)
    sales: int | None = Field(default=0, ge=0)
    scene_id: str
    official_url: str = Field(default='', max_length=1000)
    description: str = Field(default='', max_length=12000)
    image_path: str = Field(default='', max_length=1000)
    is_active: bool = True


def get_db():
    if pool is None:
        raise HTTPException(503, 'PostgreSQL is not configured or unavailable')
    return pool


def admin_auth(x_admin_token: str | None = Header(default=None)):
    expected = os.getenv('ADMIN_TOKEN', '')
    if not expected or not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(401, '管理员身份验证失败')


def recommended_ids(query: str) -> list[int]:
    q = query.lower()
    if any(x in q for x in ('茯茶', '黑茶', '喝茶', '茶叶')): return [13, 14, 19]
    if any(x in q for x in ('矿泉水', '饮用水', '桶装水', '水票')): return [1, 4, 5]
    if any(x in q for x in ('魔芋', '素毛肚', '低卡')): return [11, 12, 16]
    if any(x in q for x in ('零食', '吃的', '小吃', '特产')): return [15, 17, 20]
    return []


def serialize(row):
    return {
        'id': row['id'], 'name': row['name'],
        'price': float(row['price']) if row['price'] is not None else None,
        'sales': row['sales'], 'scene_id': row['scene_id'],
        'scene_name': SCENES.get(row['scene_id'], row['scene_id']),
        'official_url': row['official_url'], 'description': row['description'],
        'image_url': row['image_path'], 'is_active': row['is_active'],
    }

@app.get('/api/health')
def health():
    return {'status': 'ok', 'database': 'connected' if pool else 'not_configured'}

@app.get('/api/scenes')
def scenes():
    return [{'id': key, 'name': name} for key, name in SCENES.items()]

@app.get('/api/products')
async def list_products(scene: str | None = None, q: str | None = Query(default=None, max_length=120), db=Depends(get_db)):
    clauses = ['is_active = TRUE']
    args = []
    if scene:
        args.append(scene); clauses.append(f'scene_id = ${len(args)}')
    if q:
        args.append('%' + q + '%'); clauses.append(f'(name ILIKE ${len(args)} OR description ILIKE ${len(args)})')
    rows = await db.fetch('SELECT * FROM products WHERE ' + ' AND '.join(clauses) + ' ORDER BY id', *args)
    return {'items': [serialize(row) for row in rows]}

@app.get('/api/products/{product_id}')
async def get_product(product_id: int, db=Depends(get_db)):
    row = await db.fetchrow('SELECT * FROM products WHERE id=$1 AND is_active=TRUE', product_id)
    if not row: raise HTTPException(404, '商品不存在')
    return serialize(row)

@app.get('/admin', response_class=HTMLResponse)
def admin_page():
    return (BASE / 'admin.html').read_text(encoding='utf-8')

@app.post('/api/admin/products')
async def create_product(payload: ProductInput, x_admin_token: str | None = Header(default=None), db=Depends(get_db)):
    admin_auth(x_admin_token)
    if payload.scene_id not in SCENES: raise HTTPException(422, '无效的商品场景')
    product_id = await db.fetchval('SELECT COALESCE(MAX(id),0)+1 FROM products')
    row = await db.fetchrow('''INSERT INTO products(id,name,price,sales,scene_id,official_url,description,image_path,is_active)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *''', product_id, payload.name, payload.price, payload.sales,
        payload.scene_id, payload.official_url, payload.description, payload.image_path, payload.is_active)
    return serialize(row)

@app.patch('/api/admin/products/{product_id}')
async def update_product(product_id: int, payload: ProductInput, x_admin_token: str | None = Header(default=None), db=Depends(get_db)):
    admin_auth(x_admin_token)
    if payload.scene_id not in SCENES: raise HTTPException(422, '无效的商品场景')
    row = await db.fetchrow('''UPDATE products SET name=$2,price=$3,sales=$4,scene_id=$5,official_url=$6,
        description=$7,image_path=$8,is_active=$9,updated_at=NOW() WHERE id=$1 RETURNING *''', product_id, payload.name,
        payload.price, payload.sales, payload.scene_id, payload.official_url, payload.description, payload.image_path, payload.is_active)
    if not row: raise HTTPException(404, '商品不存在')
    return serialize(row)

@app.post('/api/admin/products/{product_id}/image')
async def upload_product_image(product_id: int, image: UploadFile = File(...), x_admin_token: str | None = Header(default=None), db=Depends(get_db)):
    admin_auth(x_admin_token)
    row = await db.fetchrow('SELECT id FROM products WHERE id=$1', product_id)
    if not row: raise HTTPException(404, '商品不存在')
    ext = Path(image.filename or '').suffix.lower()
    if ext not in {'.jpg','.jpeg','.png','.webp'} or image.content_type not in {'image/jpeg','image/png','image/webp'}:
        raise HTTPException(415, '仅支持 JPG、PNG、WebP 图片')
    target = UPLOADS / f'{product_id}{ext}'
    total = 0
    with target.open('wb') as out:
        while chunk := await image.read(1024 * 1024):
            total += len(chunk)
            if total > 8 * 1024 * 1024:
                out.close(); target.unlink(missing_ok=True)
                raise HTTPException(413, '图片不能超过 8 MB')
            out.write(chunk)
    image_url = f'/uploads/{target.name}'
    await db.execute('UPDATE products SET image_path=$2,updated_at=NOW() WHERE id=$1', product_id, image_url)
    return {'image_url': image_url}

@app.post('/api/admin/import-seed')
async def import_seed(x_admin_token: str | None = Header(default=None), db=Depends(get_db)):
    admin_auth(x_admin_token)
    async with db.acquire() as conn:
        async with conn.transaction():
            for item in GOODS:
                scene = item.get('c') or 'xian'
                original = SITE / 'assets' / 'goods' / f"{item['i']:02}.jpg"
                image_url = f"/uploads/{item['i']:02}.jpg"
                stored = UPLOADS / f"{item['i']:02}.jpg"
                if original.exists() and not stored.exists():
                    shutil.copy2(original, stored)
                await conn.execute('''INSERT INTO products(id,name,price,sales,scene_id,official_url,description,image_path,is_active)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,TRUE) ON CONFLICT(id) DO NOTHING''', item['i'],item['n'],
                    float(item['p']) if item.get('p') not in (None,'','—') else None,item.get('s',0),scene,item.get('u',''),
                    item.get('d',''),image_url)
    return {'imported_or_existing': len(GOODS)}

@app.post('/api/chat')
async def chat(payload: ChatRequest):
    key = os.getenv('DEEPSEEK_API_KEY')
    if not key: raise HTTPException(503, 'DeepSeek API key is not configured')
    if any(m.role not in {'user','assistant'} for m in payload.messages): raise HTTPException(422, 'Unsupported message role')
    async def stream():
        request_json={'model':'deepseek-chat','stream':True,'temperature':0.7,'max_tokens':1100,'messages':[{'role':'system','content':payload.system_prompt}]+[m.model_dump() for m in payload.messages]}
        async with httpx.AsyncClient(timeout=httpx.Timeout(90,connect=15)) as client:
            try:
                async with client.stream('POST','https://api.deepseek.com/chat/completions',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},json=request_json) as response:
                    if response.status_code!=200:
                        yield 'data: {"error":"DeepSeek request failed"}\n\n'; return
                    async for line in response.aiter_lines():
                        if not line.startswith('data:'): continue
                        data=line[5:].strip()
                        if data=='[DONE]':
                            ids=recommended_ids(payload.messages[-1].content)
                            history=''.join(m.content for m in payload.messages)
                            existing={int(a or b) for a,b in re.findall(r'\[\[商品:(\d+)\]\]|\[商品id:(\d+)\]',history)}
                            ids=[i for i in ids if i in {g['i'] for g in GOODS} and i not in existing][:3]
                            if ids:
                                event={'choices':[{'delta':{'content':''.join(f'\n[[商品:{i}]]' for i in ids)}}]}
                                yield 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n'
                            yield 'data: [DONE]\n\n'; break
                        try:
                            event=json.loads(data); delta=event.get('choices',[{}])[0].get('delta',{}); text=delta.get('content','')
                            if text:
                                delta['content']=re.sub(r'\[\[商品:\d+\]\]|\[商品id:\d+\]','',text)
                                event['choices'][0]['delta']=delta; data=json.dumps(event,ensure_ascii=False)
                        except (ValueError,IndexError,KeyError,TypeError): pass
                        yield f'data: {data}\n\n'
            except httpx.HTTPError:
                yield 'data: {"error":"DeepSeek is temporarily unavailable"}\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
