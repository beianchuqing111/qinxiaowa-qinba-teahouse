from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app


def test_health_endpoint_is_available():
    response = TestClient(app).get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_products_api_requires_configured_database(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    response = TestClient(app).get('/api/products')
    assert response.status_code == 503


def test_admin_product_page_is_served():
    response = TestClient(app).get('/admin')
    assert response.status_code == 200
    assert '商品管理' in response.text


def test_catalog_seed_is_loaded_from_current_site_source():
    from app import GOODS
    assert len(GOODS) == 72
    assert GOODS[12]['i'] == 13
