"""End-to-end, offline operations acceptance and abuse/regression tests."""
from __future__ import annotations
import asyncio
import copy
import datetime as dt
import uuid
import pytest
from sqlalchemy import func, select
from app.core.settings import get_settings
from app.models.casework import Case
from app.models.operations import ComplaintIntake, InvestigationJob, IndexedInvestigationEvent, OperationSignal
from app.models.unified import InvestigationSnapshot
from app.services.operations.intake import issue_credential
from app.services.operations.queue import claim, fence
from app.services.tracecrypt_intelligence import trace_digest
from tests.conftest import login
from tests.test_trace_endpoint import VICTIM, SERVICE, SUPPORTED_CONTRACT, SEED_EVENT


def payload(**overrides):
    data={"external_reference":"OPS-001", "title":"Synthetic complaint only", "allegation_type":"investment_scam",
        "wallets":[{"network_key":"tron", "address":VICTIM, "token_contract":SUPPORTED_CONTRACT,
                    "seed_event_reference":SEED_EVENT}], "analysis_cutoff":"2027-01-01T00:00:00Z"}
    data.update(overrides); return data


def submit(client, **kwargs):
    r=client.post('/api/v1/operations/intakes',json=payload(**kwargs))
    assert r.status_code==202,r.text
    return r.json()['data']


def test_end_to_end_intake_job_attribution_index_signals(client,db,user_a,synthetic_usdt):
    login(client,user_a); receipt=submit(client)
    assert len(receipt['jobs'])==1
    r=client.post('/api/v1/operations/process-next')
    assert r.status_code==200,r.text
    job=r.json()['data']; assert job['status'] in {'succeeded','partial'},job
    assert job['run_id']
    base=f'/api/v1/cases/{receipt["case_id"]}/investigations/{job["run_id"]}'
    trace=client.get(base).json()['data']
    summary=client.get(base+'/attribution').json()['data']
    assert summary['status']=='receiving_vasp_observed',summary
    assert summary['nearest_within_observed_scope'][0]['receiving_address']==SERVICE
    assert summary['nearest_within_observed_scope'][0]['sender_service_control']=='not_inferred'
    assert trace['intelligence']['attribution_summary']==summary
    ledger=client.get('/api/v1/operations/events?limit=1').json()['data']
    assert len(ledger['observations'])==1 and ledger['has_more']
    nextpage=client.get('/api/v1/operations/events?after='+str(ledger['next_cursor'])).json()['data']
    assert all(e['id']>ledger['next_cursor'] for e in nextpage['observations'])
    signals=client.get('/api/v1/operations/signals').json()['data']['signals']
    assert any(s['kind']=='receiving_vasp_observed' for s in signals)
    assert client.post(f'/api/v1/operations/signals/{signals[0]["id"]}/acknowledge').status_code==200
    assert client.post('/api/v1/operations/process-next').json()['data']['status']=='idle'


def test_duplicate_is_idempotent_and_changed_payload_rejected(client,db,user_a,synthetic_usdt):
    login(client,user_a); first=submit(client); second=submit(client)
    assert second['duplicate'] and second['jobs']==first['jobs']
    assert db.scalar(select(func.count()).select_from(ComplaintIntake))==1
    assert client.post('/api/v1/operations/intakes',json=payload(title='different')).status_code==409


def test_gateway_is_tenant_bound_and_expirable(client,db,org_a,org_b,user_b,synthetic_usdt):
    credential,token=issue_credential(db,organization_id=org_a.id,name='Offline test',source='agency_gateway')
    db.flush()
    r=client.post('/api/v1/integrations/complaints',json=payload(),headers={'Authorization':'Bearer '+token})
    assert r.status_code==202,r.text
    receipt=r.json()['data']; assert receipt['source']=='agency_gateway'
    login(client,user_b)
    assert client.get('/api/v1/operations/jobs').json()['data']['jobs']==[]
    assert client.get('/api/v1/operations/jobs/'+receipt['jobs'][0]['id']).status_code==404
    assert client.get('/api/v1/cases/'+receipt['case_id']).status_code==404
    credential.is_active=False;db.flush()
    assert client.post('/api/v1/integrations/complaints',json=payload(),headers={'Authorization':'Bearer '+token}).status_code==401
    assert client.post('/api/v1/integrations/complaints',json=payload()).status_code==401


def test_token_cannot_choose_organization_or_source(client,db,org_a,synthetic_usdt):
    _,token=issue_credential(db,organization_id=org_a.id,name='Test',source='ncrp_gateway')
    r=client.post('/api/v1/integrations/complaints',json=payload(organization_id=str(uuid.uuid4())),
                  headers={'Authorization':'Bearer '+token})
    assert r.status_code==422


def test_wrong_address_network_unknown_token_and_large_body_rejected(client,user_a,synthetic_usdt):
    login(client,user_a)
    for wallets in [[],[{'network_key':'tron','address':'invalid'}],
        [{'network_key':'ethereum','address':VICTIM}],
        [{'network_key':'tron','address':VICTIM,'token_contract':SERVICE}]]:
        assert client.post('/api/v1/operations/intakes',json=payload(wallets=wallets)).status_code==422
    assert client.post('/api/v1/operations/intakes',content=b' '*65537,
                       headers={'Content-Type':'application/json'}).status_code==413


def test_no_duplicate_wallet_jobs_and_discovery_not_victim_allocation(client,user_a,synthetic_usdt):
    login(client,user_a)
    wallet={'network_key':'tron','address':VICTIM}
    data=submit(client,wallets=[wallet,wallet])
    assert len(data['jobs'])==1
    r=client.post('/api/v1/operations/process-next').json()['data']
    assert r['status'] in {'succeeded','partial'},r
    run=client.get(f'/api/v1/cases/{data["case_id"]}/investigations/{r["run_id"]}').json()['data']
    assert run['trace']['scope']['case_flow_linkage']=='not_established'


def test_provider_timeout_retries_without_fake_result(client,db,user_a,synthetic_usdt,monkeypatch):
    login(client,user_a); data=submit(client)
    async def timeout(*a,**k): raise TimeoutError('DO_NOT_LOG_SECRET')
    monkeypatch.setattr('app.services.operations.queue.trace_payload',timeout)
    r=client.post('/api/v1/operations/process-next').json()['data']
    assert r['status']=='retry' and r['run_id'] is None
    assert 'DO_NOT_LOG_SECRET' not in str(r)
    assert db.scalar(select(func.count()).select_from(InvestigationSnapshot))==0
    assert client.post('/api/v1/operations/process-next').json()['data']['status']=='idle'


def test_job_claim_lease_recovery_fencing_and_cancellation(client,db,user_a,synthetic_usdt):
    login(client,user_a); data=submit(client); settings=get_settings()
    now=dt.datetime.now(dt.UTC)
    job=claim(db,settings,now=now); original=job.lease_token; ident=job.id
    assert claim(db,settings,now=now) is None
    job=claim(db,settings,now=now+dt.timedelta(seconds=2000))
    assert job.id==ident and job.attempts==2 and job.lease_token!=original
    assert not fence(db,ident,original,now=now)
    db.rollback()
    r=client.post(f'/api/v1/operations/jobs/{ident}/cancel')
    assert r.status_code==200,r.text
    assert not fence(db,ident,job.lease_token,now=now)
    db.rollback()


def test_final_expired_lease_does_not_stay_running(client,db,user_a,synthetic_usdt):
    login(client,user_a); data=submit(client); now=dt.datetime.now(dt.UTC); settings=get_settings()
    j=claim(db,settings,now=now);j.attempts=j.max_attempts;db.commit()
    assert claim(db,settings,now=now+dt.timedelta(seconds=2000)) is None
    db.refresh(j);assert j.status=='failed' and j.error_code=='lease_expired'


def test_corrupt_job_input_is_not_executed(client,db,user_a,synthetic_usdt):
    login(client,user_a); data=submit(client)
    j=db.get(InvestigationJob,uuid.UUID(data['jobs'][0]['id']));j.input_sha256='0'*64;db.flush()
    result=client.post('/api/v1/operations/process-next').json()['data']
    assert result['status']=='failed' and result['run_id'] is None


def test_new_event_index_is_tenant_scoped_and_checksum_checked(client,db,user_a,user_b,synthetic_usdt):
    login(client,user_a);submit(client);client.post('/api/v1/operations/process-next')
    assert client.get('/api/v1/operations/events').json()['data']['observations']
    login(client,user_b)
    assert client.get('/api/v1/operations/events').json()['data']['observations']==[]
    assert client.get('/api/v1/operations/signals').json()['data']['signals']==[]
    login(client,user_a)
    row=db.scalar(select(IndexedInvestigationEvent));row.observed_sha256='0'*64;db.flush()
    assert client.get('/api/v1/operations/events').status_code==409


def test_incident_window_validation(client,user_a,synthetic_usdt):
    login(client,user_a)
    for start in ['2026-09-01T00:00:00','2028-01-01T00:00:00Z']:
        assert client.post('/api/v1/operations/intakes',json=payload(incident_start=start)).status_code==422


def test_window_reaches_engine_not_just_seed_search(client,user_a,synthetic_usdt):
    login(client,user_a)
    data=submit(client,wallets=[{'network_key':'tron','address':VICTIM,'token_contract':SUPPORTED_CONTRACT}],
                incident_start='2026-12-31T00:00:00Z')
    job=client.post('/api/v1/operations/process-next').json()['data']
    assert job['status'] in {'succeeded','partial'},job
    run=client.get(f'/api/v1/cases/{data["case_id"]}/investigations/{job["run_id"]}').json()['data']
    assert run['trace']['scope']['analysis_start']=='2026-12-31T00:00:00+00:00'
    assert run['trace']['observed_transfers']==[]


def test_idle_worker_does_not_execute_writes(db):
    from sqlalchemy import event
    statements=[]
    engine=db.get_bind()
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        assert claim(db,get_settings()) is None
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert not ({'INSERT','UPDATE','DELETE'} & set(statements)), statements
