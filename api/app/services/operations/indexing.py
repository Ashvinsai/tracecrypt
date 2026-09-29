"""An indexed, exact, per-run ledger. Never substitutes for provider coverage."""
from __future__ import annotations
import datetime as dt
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.operations import IndexedInvestigationEvent
from app.services.tracecrypt_intelligence import trace_digest, verified_events


def index_snapshot(db: Session, case, snapshot) -> dict:
    if trace_digest(snapshot.trace) != snapshot.trace_sha256:
        raise ValueError("saved trace checksum mismatch")
    existing = set(db.scalars(select(IndexedInvestigationEvent.event_reference).where(
        IndexedInvestigationEvent.run_id==snapshot.id)).all())
    events, exclusions = verified_events(snapshot.trace)
    network = snapshot.trace.get("seed", {}).get("network_key", "")
    inserted = 0
    for event in events:
        if event["event_reference"] in existing:
            continue
        stamp = event.get("block_time")
        when = None
        if stamp:
            try:
                when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = None
            except (ValueError, TypeError):
                pass
        db.add(IndexedInvestigationEvent(organization_id=case.organization_id, case_id=case.id,
            run_id=snapshot.id, network_key=network, data_mode=snapshot.data_mode,
            event_reference=event["event_reference"], from_address=event["from_address"],
            to_address=event["to_address"], token_contract=event.get("asset", {}).get("token_contract") or "native",
            block_time=when, observed=event, observed_sha256=trace_digest(event)))
        inserted += 1
    db.flush()
    return {"inserted_observations": inserted, "existing_observations": len(existing),
            "excluded_events": exclusions, "scope": "saved-run ledger; not entire-chain indexing"}
