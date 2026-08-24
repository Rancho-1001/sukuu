"""Shared test fixtures.

The environment defaults below are set before anything imports ``app.core.config``,
which instantiates ``Settings()`` at module scope and would otherwise raise on a
machine with no ``.env`` file — including CI.
"""

import contextlib
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
    """A ``TestClient`` for the FastAPI app, with no database wired in."""
    pytest.importorskip("fastapi", reason="FastAPI is not installed")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def api(db_session):
    """A ``TestClient`` whose requests run inside the test's transaction.

    ``get_db`` is overridden to hand back the very session the test holds, so
    rows created by a fixture are visible to the request and everything is
    rolled back afterwards. The override yields without closing: closing here
    would end the transaction the fixture still owns.
    """
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    # The audit middleware runs after the route and would otherwise open its
    # own connection, committing rows that outlive the test's rollback.
    @contextlib.contextmanager
    def audit_session_factory():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.state.audit_session_factory = audit_session_factory
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.state.audit_session_factory = None


@pytest.fixture
def make_user(db_session):
    """Create a user with a known password and return it."""
    from app.core.security import hash_password
    from app.models import User, UserRole

    created = []

    def _make(role: UserRole, email: str | None = None, password: str = "correct-horse"):
        from uuid import uuid4

        user = User(
            email=email or f"{role.value}-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password(password),
            name=f"Test {role.value}",
            role=role,
        )
        db_session.add(user)
        db_session.flush()
        user.raw_password = password  # convenience for tests, not persisted
        created.append(user)
        return user

    return _make


@pytest.fixture
def auth_headers(api):
    """Log a user in and return the Authorization header for them."""

    def _headers(user) -> dict[str, str]:
        response = api.post(
            "/auth/login",
            data={"username": user.email, "password": user.raw_password},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _headers
