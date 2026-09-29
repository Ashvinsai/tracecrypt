"""Actual case API + real PDF/ZIP export regression, no provider calls."""
import copy
import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path
import pytest
from app.models.unified import InvestigationSnapshot
from tests.conftest import login
from tests.test_trace_endpoint import request_body, VICTIM, SUPPORTED_CONTRACT, SERVICE


def new_case(client, reference='MERGE-1'):
    r=client.post('/api/v1/cases',json={'case_reference':reference,'title':'Unified regression'})
    assert r.status_code==201, r.text
    return r.json()['data']['id']


def create_run(client, case_id):
    r=client.post(f'/api/v1/cases/{case_id}/investigations',json=request_body())
    assert r.status_code==201, r.text
    return r.json()['data']


def test_saved_trace_reopens_exports_exact_same_evidence(client,user_a,synthetic_usdt,monkeypatch):
    login(client,user_a); case_id=new_case(client); run=create_run(client,case_id)
    path=f'/api/v1/cases/{case_id}/investigations/{run["id"]}'
    assert client.get(path).json()['data']['trace']==run['trace']
    assert client.get(path).json()['data']['integrity_verified'] is True
    # Any accidental re-trace during read/export is a failure.
    async def forbidden(*args,**kwargs):
        raise AssertionError('saved endpoint re-traced')
    monkeypatch.setattr('app.routes.unified._trace',forbidden)
    assert client.get(path+'/report').status_code==200
    response=client.get(path+'/export'); assert response.status_code==200,response.text[:500]
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        manifest=json.loads(z.read('manifest.json'))
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
        assert json.loads(z.read('evidence.json'))==run['trace']
        assert json.loads(z.read('intelligence.json'))==run['intelligence']
        assert z.read('evidence.pdf').startswith(b'%PDF')
        import os
        if os.environ.get('UNIFIED_VALIDATION_OUTPUT'):
            p=Path(os.environ['UNIFIED_VALIDATION_OUTPUT']);p.mkdir(parents=True,exist_ok=True)
            (p/'synthetic-evidence.zip').write_bytes(response.content)
            (p/'synthetic-evidence.pdf').write_bytes(z.read('evidence.pdf'))
    assert client.get(path).headers['cache-control']=='no-store'


def test_foreign_organization_cannot_read_export_or_correlate(client,user_a,user_b,synthetic_usdt):
    login(client,user_a); case_id=new_case(client); run=create_run(client,case_id)
    login(client,user_b)
    base=f'/api/v1/cases/{case_id}/investigations'
    for suffix in ('','/'+run['id'],'/'+run['id']+'/export','/'+run['id']+'/report'):
        assert client.get(base+suffix).status_code==404
    assert client.get('/api/v1/workspace/correlations').json()['data']['cases_considered']==0


def test_corrupt_snapshot_cannot_be_exported(client,db,user_a,synthetic_usdt):
    login(client,user_a);case_id=new_case(client);run=create_run(client,case_id)
    row=db.get(InvestigationSnapshot,uuid.UUID(run['id']))
    altered=copy.deepcopy(row.trace);altered['scope']['coverage_status']='invented'
    row.trace=altered;db.flush()
    base=f'/api/v1/cases/{case_id}/investigations/{run["id"]}'
    assert client.get(base).status_code==409
    assert client.get(base+'/export').status_code==409


def test_saved_request_draft_is_not_a_submission(client,user_a,synthetic_usdt):
    login(client,user_a);case_id=new_case(client);run=create_run(client,case_id)
    r=client.post(f'/api/v1/cases/{case_id}/investigations/{run["id"]}/request-draft',json={
        'request_kind':'preservation','target_address':SERVICE,'requesting_agency':'Example unit',
        'requesting_officer':'Example officer','alleged_incident_summary':'Synthetic test only'})
    assert r.status_code==200,r.text
    assert r.json()['data']['submission']=='not_sent'


def test_manual_watch_poll_is_case_scoped_and_deduplicated(client,user_a,synthetic_usdt):
    login(client,user_a);case_id=new_case(client)
    path=f'/api/v1/cases/{case_id}/watches'
    response=client.post(path,json={'network_key':'tron','address':VICTIM,
        'token_contract':SUPPORTED_CONTRACT,'analysis_start':'2026-08-01T00:00:00Z'})
    assert response.status_code==201,response.text
    watch_id=response.json()['data']['id']
    first=client.post(f'{path}/{watch_id}/poll'); assert first.status_code==200,first.text
    second=client.post(f'{path}/{watch_id}/poll');assert second.status_code==200,second.text
    assert second.json()['data']['new_alerts']==0


def test_cross_origin_mutation_rejected(client,user_a):
    assert client.post('/api/v1/auth/login',json={'email':user_a.email,'password':'correct-horse-battery'},
        headers={'Origin':'https://untrusted.example'}).status_code==403
    assert client.post('/api/v1/auth/login',json={'email':user_a.email,'password':'correct-horse-battery'},
        headers={'Origin':'http://testserver'}).status_code==200


def test_workspace_static_is_self_contained(client):
    assert client.get('/workspace/').status_code==200
    assert client.get('/workspace/app.js').status_code==200
    assert client.get('/workspace/vendor/vis-network.min.js').status_code==200


def test_live_case_cannot_use_synthetic_process(client,db,user_a,synthetic_usdt):
    from app.models.casework import Case
    from app.core.settings import DataMode
    login(client,user_a);case_id=new_case(client)
    case=db.get(Case,uuid.UUID(case_id));case.data_mode=DataMode.LIVE;db.flush()
    assert client.post(f'/api/v1/cases/{case_id}/investigations',json=request_body()).status_code==409


def test_cutoff_must_include_timezone(client,user_a,synthetic_usdt):
    login(client,user_a);case_id=new_case(client)
    assert client.post(f'/api/v1/cases/{case_id}/investigations',json=request_body(
        analysis_cutoff='2026-09-27T00:00:00')).status_code==422


def test_asset_selected_by_uuid_matches_ui_contract(client,user_a,synthetic_usdt):
    login(client,user_a);case_id=new_case(client)
    response=client.post(f'/api/v1/cases/{case_id}/investigations',json=request_body(
        asset_id=str(synthetic_usdt.id),token_contract=None))
    assert response.status_code==201,response.text


def test_invalid_asset_uuid_is_validation_error_not_server_error(client,user_a,synthetic_usdt):
    login(client,user_a);case_id=new_case(client)
    assert client.post(f'/api/v1/cases/{case_id}/investigations',json=request_body(
        asset_id='invalid')).status_code==422
