"""Test fixtures.

The suite runs on SQLite by default (D012) and on PostgreSQL when
``CFA_DATABASE_URL`` points at one; CI runs both, because native enums,
NUMERIC(78,0) and JSONB behave differently and the invariants under test are
exactly the ones a single dialect would hide.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("CFA_APP_ENV", "test")
os.environ.setdefault("CFA_DATA_MODE", "SYNTHETIC")
os.environ.setdefault(
    "CFA_SECRET_KEY", "test-secret-key-that-is-long-enough-for-the-validator"
)
#: Tests get their own database file, wiped at session start. Set
#: CFA_DATABASE_URL to run the same suite against PostgreSQL.
_DEFAULT_TEST_DB = Path(__file__).resolve().parents[2] / "var" / "cfa-test.db"
_DEFAULT_TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CFA_DATABASE_URL", f"sqlite+pysqlite:///{_DEFAULT_TEST_DB}")

from app.core.security import hash_password  # noqa: E402
from app.core.settings import DataMode, get_settings  # noqa: E402
from app.db.base import Base, get_db, make_engine  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models.chain import Asset, Network  # noqa: E402
from app.models.enums import AssetKind, NetworkFamily  # noqa: E402
from app.models.identity import Membership, Organization, User  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FILE = REPO_ROOT / "fixtures" / "tron_synthetic_case_alpha.json"


@pytest.fixture(scope="session")
def engine():
    settings = get_settings()
    eng = make_engine(settings.database_url)
    try:
        with eng.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover - environment problem, not a test failure
        pytest.skip(f"database not reachable at {settings.database_url}: {exc}")
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """A session on a transaction that is rolled back after every test."""
    connection = engine.connect()
    transaction = connection.begin()
    #: ``create_savepoint`` makes a commit inside application code end a SAVEPOINT
    #: rather than the outer transaction, so rolling back below really does undo
    #: everything the test did.
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def tron(db: Session) -> Network:
    network = Network(
        key="tron",
        display_name="TRON mainnet",
        family=NetworkFamily.account,
        chain_id=None,
        native_asset_symbol="TRX",
        is_supported=True,
    )
    db.add(network)
    db.flush()
    return network


@pytest.fixture
def ethereum(db: Session) -> Network:
    network = Network(
        key="ethereum",
        display_name="Ethereum mainnet",
        family=NetworkFamily.account,
        chain_id=1,
        native_asset_symbol="ETH",
        is_supported=False,
    )
    db.add(network)
    db.flush()
    return network


@pytest.fixture
def synthetic_usdt(db: Session, tron: Network) -> Asset:
    asset = Asset(
        network_id=tron.id,
        kind=AssetKind.token,
        token_contract="TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
        decimals=6,
        display_symbol="USDT-SYN",
        issuer_reference="synthetic fixture; not a real issuer reference",
        verified_at=None,
        is_supported=True,
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(asset)
    db.flush()
    return asset


@pytest.fixture
def org_a(db: Session) -> Organization:
    org = Organization(name="Cyber Cell A", slug=f"cell-a-{uuid.uuid4().hex[:6]}")
    db.add(org)
    db.flush()
    return org


@pytest.fixture
def org_b(db: Session) -> Organization:
    org = Organization(name="Cyber Cell B", slug=f"cell-b-{uuid.uuid4().hex[:6]}")
    db.add(org)
    db.flush()
    return org


def _make_user(db: Session, org: Organization, email: str, password: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=email.split("@")[0],
    )
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role="investigator"))
    db.flush()
    return user


@pytest.fixture
def user_a(db: Session, org_a: Organization) -> User:
    return _make_user(db, org_a, f"a-{uuid.uuid4().hex[:6]}@example.test", "correct-horse-battery")


@pytest.fixture
def user_b(db: Session, org_b: Organization) -> User:
    return _make_user(db, org_b, f"b-{uuid.uuid4().hex[:6]}@example.test", "correct-horse-battery")


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    fastapi_app.dependency_overrides[get_db] = lambda: db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


def login(client: TestClient, user: User, password: str = "correct-horse-battery"):
    return client.post("/api/v1/auth/login", json={"email": user.email, "password": password})


@pytest.fixture
def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
