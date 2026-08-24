"""Shared test fixtures.

The environment defaults below are set before anything imports ``app.core.config``,
which instantiates ``Settings()`` at module scope and would otherwise raise on a
machine with no ``.env`` file — including CI.
"""

import os
import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://sukuu:sukuu@localhost:5432/sukuu_test")
os.environ.setdefault("JWT_SECRET", "test-secret-never-used-in-production")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def database_url() -> str:
    """Connection string for the throwaway test database."""
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def engine(database_url: str):
    """A SQLAlchemy engine, or a skip when no Postgres is reachable.

    Tests that need real SQL are marked ``db``. They are skipped rather than
    failed on a machine without Postgres so that ``pytest`` stays useful during
    local development; CI runs a Postgres service container, so nothing is
    silently skipped where it matters.
    """
    sqlalchemy = pytest.importorskip("sqlalchemy", reason="SQLAlchemy is not installed")

    engine = sqlalchemy.create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(f"No Postgres reachable at {database_url}: {exc}")

    _migrate(database_url)

    yield engine
    engine.dispose()


def _migrate(database_url: str) -> None:
    """Bring the test database to head.

    Deliberately runs the real migrations rather than ``Base.metadata.create_all``.
    Creating tables straight from the models would test the models against
    themselves and never notice a migration that drifted from them - which is
    exactly the failure worth catching, since production only ever sees the
    migrations.
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "app" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture
def db_session(engine):
    """A session wrapped in a transaction that is rolled back after each test.

    Every test therefore sees a clean database without paying to recreate the
    schema between tests.
    """
    from sqlalchemy.orm import Session

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, future=True)
    try:
        yield session
    finally:
        session.close()
        # A test that provoked an IntegrityError has already had its
        # transaction aborted; rolling back again warns rather than helps.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def client():
    """A ``TestClient`` for the FastAPI app."""
    pytest.importorskip("fastapi", reason="FastAPI is not installed")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
