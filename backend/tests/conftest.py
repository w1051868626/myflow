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
