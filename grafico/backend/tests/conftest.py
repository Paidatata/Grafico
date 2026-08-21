import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TEMP_DB_DIR = tempfile.mkdtemp(prefix="grafico-test-db-")
os.environ["GRAFICO_DB_PATH"] = str(Path(_TEMP_DB_DIR) / "test_railway.db")

import pytest


@pytest.fixture(autouse=True)
def _clean_tables():
    from src import service
    service.set_current_schedule_id(1)
    yield
    from src.db import Base, engine

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    service.set_current_schedule_id(1)


@pytest.fixture()
def db_session():
    from src.db import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def app_client():
    from fastapi.testclient import TestClient
    from src.app import app

    with TestClient(app) as client:
        yield client
