import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.map_seed import seed_map


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        mqtt_enabled=False, mqtt_host="localhost", mqtt_port=1883,
        mqtt_username=None, mqtt_password=None, mqtt_tls=False,
        admin_token="test-token", timezone="Asia/Seoul",
        crop_dir=str(tmp_path / "crops"),
    )


@pytest.fixture
def client(settings):
    """앱 + 빈 DB (지도 데이터 없음)."""
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def app_client(client):
    """앱 + 지도 기본 데이터(b2.json과 같은 구역 2·카메라 2·칸 8)."""
    with client.app.state.db.SessionLocal() as s:
        seed_map(s)
    return client


@pytest.fixture
def db(app_client):
    """app_client와 같은 DB의 세션 (서비스 함수 직접 호출용)."""
    with app_client.app.state.db.SessionLocal() as s:
        yield s
