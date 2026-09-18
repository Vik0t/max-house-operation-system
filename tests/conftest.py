import os
from pathlib import Path

TEST_DB = Path("/tmp/dompuls-pytest.sqlite3")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["MAX_MODE"] = "simulated"
os.environ["LLM_MODE"] = "deterministic"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app
from app.seed import reset_and_seed


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_and_seed()
    with TestClient(app) as test_client:
        yield test_client

