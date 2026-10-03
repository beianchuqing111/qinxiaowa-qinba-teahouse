import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app, recommended_ids
from fastapi.testclient import TestClient


def test_health_endpoint_is_available():
    response = TestClient(app).get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_chat_requires_configured_deepseek_key(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    response = TestClient(app).post('/api/chat', json={'system_prompt': 'test prompt', 'messages': [{'role': 'user', 'content': '你好'}]})
    assert response.status_code == 503


def test_tea_query_selects_real_tea_product_ids():
    assert recommended_ids('请推荐茯茶') == [13, 14, 19]


def test_non_product_question_does_not_force_product_cards():
    assert recommended_ids('你好呀，介绍一下你自己') == []


def test_actual_page_parser_and_product_images_exist():
    page = Path(__file__).resolve().parents[1] / 'xiyouji-website' / 'index.html'
    text = page.read_text(encoding='utf-8')
    match = re.search(r'const GOODS = (.*?);\nconst SCENES', text, re.S)
    assert match
    assert len(__import__('json').loads(match.group(1))) == 72
    for product_id in recommended_ids('茯茶'):
        assert (page.parent / 'assets' / 'goods' / f'{product_id:02}.jpg').exists()
