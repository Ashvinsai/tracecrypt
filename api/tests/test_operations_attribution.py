"""Conflicting labels and nearest-service ties never silently select an owner."""
import copy
from dataclasses import replace
import pytest
from tests.test_tracer import (anchor,registry,tracer,ScriptedAdapter,transfer,ASSET,A,B,C,SERVICE,T0,CUTOFF)
from app.services.operations.attribution import attribution_summary


def test_conflicting_accepted_identities_do_not_terminate():
    first=anchor(SERVICE);second=replace(first,entity_name='Other FICTIONAL exchange')
    labels=registry(first,second)
    assert labels.has_active_conflict('tron',SERVICE,T0)
    assert labels.terminating_anchor('tron',SERVICE,T0) is None


def test_conflicting_wallet_roles_do_not_pick_csv_row_order():
    first=anchor(SERVICE);second=replace(first,address_role='hot_wallet')
    assert registry(first,second).terminating_anchor('tron',SERVICE,T0) is None
    assert registry(second,first).terminating_anchor('tron',SERVICE,T0) is None


def test_duplicate_independent_same_conclusion_remains_usable():
    first=anchor(SERVICE);second=replace(first,source_reference='another synthetic evidence source')
    assert registry(first,second).terminating_anchor('tron',SERVICE,T0) is not None


@pytest.mark.asyncio
async def test_conflict_produces_limitation_and_trace_continues():
    events=[transfer('SYNTHETIC-a:0',A,SERVICE,100,1),transfer('SYNTHETIC-b:0',SERVICE,B,80,2)]
    first=anchor(SERVICE);labels=registry(first,replace(first,entity_name='Other FICTIONAL exchange'))
    result=await tracer(ScriptedAdapter(events),labels).trace(seed_address=A,asset=ASSET,analysis_cutoff=CUTOFF)
    data=result.to_json()
    assert any(l['code']=='conflicting_service_labels' for l in data['limitations'])
    assert any(e['to_address']==B for e in data['observed_transfers'])
    assert attribution_summary(data)['status']=='unresolved'


@pytest.mark.asyncio
async def test_equally_near_vasps_are_all_retained_with_actual_hop_counts():
    events=[transfer('SYNTHETIC-a:0',A,B,50,1),transfer('SYNTHETIC-b:0',A,C,50,2)]
    labels=registry(anchor(B),replace(anchor(C),entity_name='Second FICTIONAL exchange'))
    result=await tracer(ScriptedAdapter(events),labels).trace(seed_address=A,asset=ASSET,analysis_cutoff=CUTOFF)
    summary=attribution_summary(result.to_json())
    assert summary['minimum_observed_transfer_hops']==1
    assert len(summary['nearest_within_observed_scope'])==2
    assert {e['receiving_address'] for e in summary['nearest_within_observed_scope']}=={B,C}
