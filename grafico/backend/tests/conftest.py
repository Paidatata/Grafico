import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _use_temp_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("data") / "test_railway.db"
    os.environ["GRAFICO_DB_PATH"] = str(db_path)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    from src.db import Base, engine

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db_session():
    from src.db import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
