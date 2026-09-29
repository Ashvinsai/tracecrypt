"""B02-B04: server-side authorization on every case route (T1)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings import DataMode
from app.models.casework import Case
from app.models.identity import Organization, User
from tests.conftest import login


def _case_for(db: Session, org: Organization, reference: str = "CASE-001") -> Case:
    case = Case(
        organization_id=org.id,
        case_reference=reference,
        title="Fixture case",
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(case)
    db.flush()
    return case


def test_unauthenticated_rejected(client: TestClient, db: Session, org_a: Organization) -> None:
    """B02: no session, no case data."""
    case = _case_for(db, org_a)
    assert client.get(f"/api/v1/cases/{case.id}").status_code == 401
    assert client.get("/api/v1/cases").status_code == 401
    created = client.post("/api/v1/cases", json={"case_reference": "X", "title": "Y"})
    assert created.status_code == 401


def test_cross_org_case_is_404(
    client: TestClient, db: Session, org_b: Organization, user_a: User, user_b: User
) -> None:
    """B03: a foreign case is indistinguishable from one that does not exist."""
    foreign = _case_for(db, org_b, "CASE-B-1")
    login(client, user_a)

    response = client.get(f"/api/v1/cases/{foreign.id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    missing = client.get("/api/v1/cases/00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404
    assert response.json() == missing.json()


def test_cross_org_seed_rejected(
    client: TestClient, db: Session, org_b: Organization, user_a: User, user_b: User, tron
) -> None:
    """B04: writing to a foreign case fails the same way reading does."""
    foreign = _case_for(db, org_b, "CASE-B-2")
    login(client, user_a)
    response = client.post(
        f"/api/v1/cases/{foreign.id}/seeds",
        json={
            "mode": "address_discovery",
            "network_key": "tron",
            "address": "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
        },
    )
    assert response.status_code == 404


def test_case_list_is_org_scoped(
    client: TestClient, db: Session, org_a: Organization, org_b: Organization, user_a: User
) -> None:
    mine = _case_for(db, org_a, "CASE-A-1")
    _case_for(db, org_b, "CASE-B-3")
    login(client, user_a)
    body = client.get("/api/v1/cases").json()["data"]
    assert [c["id"] for c in body] == [str(mine.id)]
