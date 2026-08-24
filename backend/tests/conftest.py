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


@pytest.fixture
def token_for(api, make_user):
    """Mint a token for a fresh user of the given role."""

    def _token(role):
        user = make_user(role)
        response = api.post(
            "/auth/login", data={"username": user.email, "password": user.raw_password}
        )
        assert response.status_code == 200, response.text
        return user, {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _token


@pytest.fixture
def headers_for(token_for):
    """The Authorization header for a fresh user of the given role."""

    def _headers(role) -> dict[str, str]:
        return token_for(role)[1]

    return _headers


@pytest.fixture
def admin_headers(headers_for):
    from app.models import UserRole

    return headers_for(UserRole.ADMIN)


@pytest.fixture
def staff_headers(headers_for):
    from app.models import UserRole

    return headers_for(UserRole.STAFF)


@pytest.fixture
def parent_headers(headers_for):
    from app.models import UserRole

    return headers_for(UserRole.PARENT)


@pytest.fixture
def make_class(db_session):
    """A class, with a name unique enough not to collide with seed data."""
    from uuid import uuid4

    from app.models import SchoolClass

    def _make(name: str | None = None, academic_year: str = "2026", archived_at=None):
        school_class = SchoolClass(
            name=name or f"Class {uuid4().hex[:8]}",
            academic_year=academic_year,
            archived_at=archived_at,
        )
        db_session.add(school_class)
        db_session.flush()
        return school_class

    return _make


@pytest.fixture
def make_fee_type(db_session):
    from uuid import uuid4

    from app.models import BillingPeriod, FeeType

    def _make(
        name: str | None = None,
        default_amount: str = "250.00",
        billing_period: BillingPeriod = BillingPeriod.TERM,
        description: str | None = None,
    ):
        from decimal import Decimal

        fee_type = FeeType(
            name=name or f"Fee {uuid4().hex[:8]}",
            default_amount=Decimal(default_amount),
            billing_period=billing_period,
            description=description,
        )
        db_session.add(fee_type)
        db_session.flush()
        return fee_type

    return _make


@pytest.fixture
def make_student(db_session):
    from uuid import uuid4

    from app.models import Student, StudentStatus

    def _make(
        first_name: str = "Ama",
        last_name: str = "Mensah",
        admission_number: str | None = None,
        school_class=None,
        parent=None,
        status: StudentStatus = StudentStatus.ACTIVE,
    ):
        student = Student(
            first_name=first_name,
            last_name=last_name,
            admission_number=admission_number or uuid4().hex[:12],
            school_class=school_class,
            parent=parent,
            status=status,
        )
        db_session.add(student)
        db_session.flush()
        return student

    return _make


@pytest.fixture
def query_counter(engine):
    """Count the SQL statements a block of code issues.

    The point is not the absolute number - that shifts when a route grows a
    join - but that it stays *flat* as rows are added. An N+1 is precisely a
    count that tracks the size of the result set, so the tests compare a
    one-row page against a many-row page rather than asserting a magic number.
    """
    import contextlib

    from sqlalchemy import event

    @contextlib.contextmanager
    def _counter():
        statements: list[str] = []

        def before(_conn, _cursor, statement, _params, _context, _executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", before)
        try:
            yield statements
        finally:
            event.remove(engine, "before_cursor_execute", before)

    return _counter


@pytest.fixture
def make_fee_assignment(db_session):
    from decimal import Decimal

    from app.models import FeeAssignment

    def _make(student, fee_type, amount=None, period_label="Term 1 2026", due_date=None):
        assignment = FeeAssignment(
            student=student,
            fee_type=fee_type,
            amount=Decimal(amount) if amount is not None else fee_type.default_amount,
            period_label=period_label,
            due_date=due_date,
        )
        db_session.add(assignment)
        db_session.flush()
        return assignment

    return _make


@pytest.fixture
def make_payment(db_session):
    """Record a payment through the real service, lock and all."""
    from decimal import Decimal

    from app.models import PaymentMethod
    from app.services.payments import record_payment

    def _make(assignment, amount, recorded_by=None, method=PaymentMethod.CASH, **kwargs):
        payment = record_payment(
            db_session,
            fee_assignment_id=assignment.id,
            amount=Decimal(str(amount)),
            method=method,
            recorded_by_id=recorded_by.id if recorded_by is not None else None,
            **kwargs,
        )
        db_session.flush()
        return payment

    return _make
