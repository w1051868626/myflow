import os
import tempfile

# Isolated database and artifacts; never touch a developer's data directory.
_data = tempfile.TemporaryDirectory(prefix="myflow-test-")
os.environ["MYFLOW_DATA_DIR"] = _data.name

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import engine


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    _data.cleanup()


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def block_real_provider_http(monkeypatch):
    """Standard acceptance never sends HTTPX requests to a real provider."""
    import httpx

    def blocked(*args, **kwargs):
        raise AssertionError('Real HTTP is disabled in tests; use httpx.MockTransport')

    async def blocked_async(*args, **kwargs):
        blocked()

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', blocked_async)
