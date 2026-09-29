"""Seed a local demo: one organization, one investigator, and the synthetic fixture.

Everything written here is SYNTHETIC. The addresses and the service name are
deliberately fictional and must never reach a production label database.
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.core.settings import AppEnv, DataMode, get_settings  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.attribution import AttributionEvidence, Entity, LabelAssertion  # noqa: E402
from app.models.casework import Case, CaseSeed  # noqa: E402
from app.models.chain import Address, Network, TransferEvent  # noqa: E402
from app.models.enums import (  # noqa: E402
    AddressRole,
    AssertionType,
    AttributionStatus,
    EntityType,
    NetworkFamily,
    ReviewState,
    SeedMode,
)
from app.models.identity import Membership, Organization, User  # noqa: E402
from app.services.fixtures import load_fixture_into_db  # noqa: E402

FIXTURE = REPO_ROOT / "fixtures" / "tron_synthetic_case_alpha.json"
DEMO_EMAIL = "investigator@example.test"
DEMO_PASSWORD = "demo-password-change-me"  # noqa: S105 - local demo account only
SERVICE_DEPOSIT = "TBvGC1Nd8i5wmj185HTdoTWAZPmRUTFBZz"
VICTIM = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"


def main() -> int:
    settings = get_settings()
    if settings.data_mode is not DataMode.SYNTHETIC or settings.app_env is AppEnv.prod:
        print("refusing to seed demo data outside a non-production SYNTHETIC process", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        network = db.execute(select(Network).where(Network.key == "tron")).scalar_one_or_none()
        if network is None:
            network = Network(
                key="tron",
                display_name="TRON mainnet",
                family=NetworkFamily.account,
                chain_id=None,
                native_asset_symbol="TRX",
                is_supported=True,
                notes="Only network supported in phase 02.",
            )
            db.add(network)
            db.flush()

        org = db.execute(
            select(Organization).where(Organization.slug == "demo-cyber-cell")
        ).scalar_one_or_none()
        if org is None:
            org = Organization(name="Demo Cyber Cell", slug="demo-cyber-cell")
            db.add(org)
            db.flush()

        user = db.execute(select(User).where(User.email == DEMO_EMAIL)).scalar_one_or_none()
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                display_name="Demo Investigator",
            )
            db.add(user)
            db.flush()
            db.add(Membership(user_id=user.id, organization_id=org.id, role="investigator"))
            db.flush()

        # Preparing an existing local database must not insert duplicate events
        # or delete case evidence. Only import a pristine fixture event set.
        fixture = json.loads(FIXTURE.read_text())
        expected = {event["event_reference"] for event in fixture["events"]}
        existing = db.scalars(select(TransferEvent).where(TransferEvent.network_id == network.id,
            TransferEvent.event_reference.in_(expected))).all()
        if existing:
            if {row.event_reference for row in existing} != expected or any(row.data_mode is not DataMode.SYNTHETIC for row in existing):
                raise RuntimeError("Existing fixture events are incomplete or belong to another mode. Preserve the database and investigate; setup will not overwrite evidence.")
            result = SimpleNamespace(events_loaded=0, addresses_loaded=0, assets_loaded=0)
            print("Synthetic fixture event set already present; retained without overwriting.")
        else:
            result = load_fixture_into_db(db, FIXTURE, network=network, data_mode=DataMode.SYNTHETIC)

        # One accepted service label, so phase 05 has a boundary to stop at.
        entity = db.execute(
            select(Entity).where(Entity.name == "Northwind Exchange (FICTIONAL)")
        ).scalar_one_or_none()
        if entity is None:
            entity = Entity(
                name="Northwind Exchange (FICTIONAL)",
                entity_type=EntityType.exchange,
                jurisdiction="XX",
                data_mode=DataMode.SYNTHETIC,
            )
            db.add(entity)
            db.flush()

            evidence = AttributionEvidence(
                source_type="synthetic_fixture",
                source_reference="fixtures/tron_synthetic_case_alpha.json",
                retrieval_date=dt.datetime.now(dt.UTC),
                methodology=(
                    "Invented for demonstration. This is not evidence about any real service."
                ),
                reviewer="demo seed script",
                reuse_terms="internal demo only",
            )
            db.add(evidence)
            db.flush()

            deposit = db.execute(
                select(Address).where(
                    Address.network_id == network.id,
                    Address.canonical_address == SERVICE_DEPOSIT,
                )
            ).scalar_one()
            db.add(
                LabelAssertion(
                    address_id=deposit.id,
                    entity_id=entity.id,
                    assertion_type=AssertionType.service_control,
                    address_role=AddressRole.deposit,
                    evidence_id=evidence.id,
                    review_state=ReviewState.accepted,
                    attribution_status=AttributionStatus.supported,
                    valid_from=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                    last_verified_at=dt.datetime.now(dt.UTC),
                    label_set_version=settings.label_set_version,
                    data_mode=DataMode.SYNTHETIC,
                    created_by="demo seed script",
                )
            )

        case = db.execute(
            select(Case).where(
                Case.organization_id == org.id, Case.case_reference == "DEMO-2026-0001"
            )
        ).scalar_one_or_none()
        if case is None:
            case = Case(
                organization_id=org.id,
                case_reference="DEMO-2026-0001",
                title="Synthetic demonstration incident",
                data_mode=DataMode.SYNTHETIC,
                created_by=user.id,
            )
            db.add(case)
            db.flush()
            victim = db.execute(
                select(Address).where(
                    Address.network_id == network.id, Address.canonical_address == VICTIM
                )
            ).scalar_one()
            db.add(
                CaseSeed(
                    case_id=case.id,
                    mode=SeedMode.incident,
                    network_id=network.id,
                    address_id=victim.id,
                    amount_base_units=100_000_000,
                    incident_time=dt.datetime(2026, 8, 1, 10, 10, tzinfo=dt.UTC),
                )
            )

        db.commit()
        print(
            f"seeded SYNTHETIC demo: {result.events_loaded} events, "
            f"{result.addresses_loaded} addresses, {result.assets_loaded} assets"
        )
        print(f"login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
