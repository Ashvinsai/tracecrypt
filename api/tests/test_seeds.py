"""Seed intake rules (PRD section 2)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings import DataMode
from app.models.casework import Case
from app.models.identity import Organization, User
from tests.conftest import login

VICTIM = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"


def _case(db: Session, org: Organization) -> Case:
    case = Case(
        organization_id=org.id,
        case_reference="CASE-SEED",
        title="Seed rules",
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(case)
    db.flush()
    return case


def test_incident_seed_requires_an_asset(
    client: TestClient, db: Session, org_a: Organization, user_a: User, tron
) -> None:
    case = _case(db, org_a)
    login(client, user_a)
    response = client.post(
        f"/api/v1/cases/{case.id}/seeds",
        json={"mode": "incident", "network_key": "tron", "address": VICTIM},
    )
    assert response.status_code == 422
    assert "asset_id" in str(response.json())


def test_address_discovery_refuses_an_amount(
    client: TestClient, db: Session, org_a: Organization, user_a: User, tron
) -> None:
    """Address-only input asserts nothing about victim funds, so it takes no amount."""
    case = _case(db, org_a)
    login(client, user_a)
    response = client.post(
        f"/api/v1/cases/{case.id}/seeds",
        json={
            "mode": "address_discovery",
            "network_key": "tron",
            "address": VICTIM,
            "amount_base_units": "100000000",
        },
    )
    assert response.status_code == 422


def test_address_discovery_seed_is_not_case_linked(
    client: TestClient, db: Session, org_a: Organization, user_a: User, tron
) -> None:
    case = _case(db, org_a)
    login(client, user_a)
    response = client.post(
        f"/api/v1/cases/{case.id}/seeds",
        json={"mode": "address_discovery", "network_key": "tron", "address": VICTIM},
    )
    assert response.status_code == 201
    assert response.json()["data"]["case_flow_linkage"] == "not_established"


def test_incident_seed_keeps_amount_as_string(
    client: TestClient, db: Session, org_a: Organization, user_a: User, tron, synthetic_usdt
) -> None:
    case = _case(db, org_a)
    login(client, user_a)
    response = client.post(
        f"/api/v1/cases/{case.id}/seeds",
        json={
            "mode": "incident",
            "network_key": "tron",
            "address": VICTIM,
            "asset_id": str(synthetic_usdt.id),
            "amount_base_units": "100000000",
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["amount_base_units"] == "100000000"
    assert isinstance(data["amount_base_units"], str)
    assert data["case_flow_linkage"] == "established"


def test_invalid_address_is_rejected_for_the_stated_network(
    client: TestClient, db: Session, org_a: Organization, user_a: User, tron
) -> None:
    case = _case(db, org_a)
    login(client, user_a)
    response = client.post(
        f"/api/v1/cases/{case.id}/seeds",
        json={
            "mode": "address_discovery",
            "network_key": "tron",
            "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        },
    )
    assert response.status_code == 422
