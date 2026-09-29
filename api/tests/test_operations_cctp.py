"""Checked CCTP: captured component tests and mocked live HTTP, never live funds."""
import copy
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from app.services.operations.cctp import (CctpRequest,EvidenceRejected,verify_components,acquire)
from tests.conftest import login

ROOT=Path(__file__).resolve().parents[2]
RAW=ROOT/'var/live-validation/20260927-cctp-v2-eth-base-live-001/raw'


@pytest.fixture
def evidence():
    def r(n):return json.loads(next(RAW.glob(n+'-*')).read_text())['body']['result']
    src,dst=r('0002'),r('0014')
    return {'ethereum_chain_id':'0x1','base_chain_id':r('0001'),
        'source_tx_hash':src['transactionHash'],'destination_tx_hash':dst['transactionHash'],
        'source_receipt':src,'source_block':r('0003'),'source_finalized':r('0004'),
        'destination_receipt':dst,'destination_block':r('0015'),'destination_finalized':r('0016'),
        'iris':json.loads(next(RAW.glob('0005-*')).read_text())['body']}


def test_captured_components_reconcile_with_declared_chain_context(evidence):
    # Original capture omitted Ethereum eth_chainId; supplied 1 is explicit test
    # chain context, not a claim that an omitted RPC check occurred historically.
    result=verify_components(evidence,data_mode='RECORDED_PUBLIC')
    assert result['status']=='matched_finalized_provider_evidence'
    assert result['source_amount_base_units']==result['destination_amount_base_units']=='9391319'
    assert result['attestation_signature_verified'] is False


@pytest.mark.parametrize('mutation',["unknown_execution","unfinalized","noncanonical","wrong_chain","removed_log","wrong_recipient","iris_immutable","wrong_nonce","duplicate_message"])
def test_malformed_or_unverified_components_never_match(evidence,mutation):
    if mutation=='unknown_execution':evidence['source_receipt'].pop('status')
    elif mutation=='unfinalized':evidence['destination_finalized']['number']='0x1'
    elif mutation=='noncanonical':evidence['destination_block']['hash']='0x'+'0'*64
    elif mutation=='wrong_chain':evidence['ethereum_chain_id']='0x38'
    elif mutation=='removed_log':evidence['source_receipt']['logs'][0]['removed']=True
    elif mutation=='wrong_recipient':
        for row in evidence['destination_receipt']['logs']:
            if row.get('topics') and row['topics'][0].startswith('0x50c55e'):
                row['topics'][1]='0x'+'0'*24+'1'*40
    elif mutation=='iris_immutable':
        msg=evidence['iris']['messages'][0];raw=bytearray.fromhex(msg['message'][2:]);raw[50]^=1;msg['message']='0x'+raw.hex()
    elif mutation=='wrong_nonce':evidence['iris']['messages'][0]['eventNonce']='0x'+'2'*64
    elif mutation=='duplicate_message':
        receipt=evidence['destination_receipt'];row=copy.deepcopy(receipt['logs'][-1]);row['logIndex']='0xffff';receipt['logs'].append(row)
    with pytest.raises((EvidenceRejected,ValueError,TypeError)):
        verify_components(evidence,data_mode='RECORDED_PUBLIC')


def mock_client(evidence,*,wrong_chain=False):
    def handler(request):
        if request.method=='GET':return httpx.Response(200,json=evidence['iris'])
        payload=json.loads(request.content);network='source' if request.url.host=='ethereum.test' else 'destination'
        method,params=payload['method'],payload['params']
        if method=='eth_chainId':result='0x38' if wrong_chain else ('0x1' if network=='source' else '0x2105')
        elif method=='eth_getTransactionReceipt':result=evidence[network+'_receipt']
        elif method=='eth_getBlockByNumber':result=evidence[network+('_finalized' if params[0]=='finalized' else '_block')]
        elif method=='eth_getLogs':
            result=[r for r in evidence['destination_receipt']['logs'] if r.get('topics') and r['topics'][0].startswith('0xff48c13e')]
        else:raise AssertionError(method)
        return httpx.Response(200,json={'jsonrpc':'2.0','id':payload['id'],'result':result})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_live_connector_execution_with_mocked_rpc_checks_both_chains(monkeypatch,evidence):
    client=mock_client(evidence)
    monkeypatch.setattr('app.services.operations.cctp.httpx.AsyncClient',lambda **kw:client)
    settings=SimpleNamespace(ethereum_rpc_url='https://ethereum.test/secret-key',base_rpc_url='https://base.test/secret-key')
    result=await acquire(settings,CctpRequest(source_tx_hash=evidence['source_tx_hash'],destination_tx_hash=evidence['destination_tx_hash']))
    assert result['result']['status']=='matched_finalized_provider_evidence'
    assert [r['method'] for r in result['acquisitions'][:2]]==['eth_chainId','eth_chainId']
    assert 'secret-key' not in json.dumps(result)


@pytest.mark.asyncio
async def test_bounded_nonce_destination_discovery(monkeypatch,evidence):
    client=mock_client(evidence);monkeypatch.setattr('app.services.operations.cctp.httpx.AsyncClient',lambda **kw:client)
    height=int(evidence['destination_receipt']['blockNumber'],16)
    result=await acquire(SimpleNamespace(ethereum_rpc_url='https://ethereum.test',base_rpc_url='https://base.test'),
        CctpRequest(source_tx_hash=evidence['source_tx_hash'],destination_from_block=height-2,destination_to_block=height+2))
    assert result['result']['destination_tx_hash']==evidence['destination_tx_hash']
    assert result['result']['acquisition_scope']['all_time_search'] is False


@pytest.mark.asyncio
async def test_wrong_rpc_chain_fails_before_receipts(monkeypatch,evidence):
    client=mock_client(evidence,wrong_chain=True);monkeypatch.setattr('app.services.operations.cctp.httpx.AsyncClient',lambda **kw:client)
    with pytest.raises(EvidenceRejected,match='wrong networks'):
        await acquire(SimpleNamespace(ethereum_rpc_url='https://ethereum.test',base_rpc_url='https://base.test'),CctpRequest(source_tx_hash=evidence['source_tx_hash']))


def test_protocol_api_cannot_convert_synthetic_case_into_live_evidence(client,user_a,evidence):
    login(client,user_a)
    case=client.post('/api/v1/cases',json={'case_reference':'CC-001','title':'Synthetic test only'}).json()['data']
    response=client.post(f'/api/v1/cases/{case["id"]}/cross-chain/cctp',json={'source_tx_hash':evidence['source_tx_hash']})
    assert response.status_code==409,response.text


def test_invalid_destination_scope_rejected():
    with pytest.raises(ValueError):CctpRequest(source_tx_hash='0x'+'1'*64,destination_from_block=1)
    with pytest.raises(ValueError):CctpRequest(source_tx_hash='0x'+'1'*64,destination_from_block=1,destination_to_block=100000)


def test_saved_review_tenant_scope_integrity_and_continuation(client,db,user_a,user_b,org_a,evidence,monkeypatch):
    from app.core.settings import get_settings,DataMode,LabelSource
    from app.models.casework import Case
    from app.models.chain import Network,Asset
    from app.models.enums import NetworkFamily,AssetKind
    from app.models.operations import CrossChainReview,InvestigationJob
    from app.services.tracecrypt_intelligence import trace_digest
    from sqlalchemy import select
    live=get_settings().model_copy(update={'data_mode':DataMode.LIVE,'label_source':LabelSource.reviewed_sets,
        'ethereum_rpc_url':'https://ethereum.test','base_rpc_url':'https://base.test'})
    client.app.dependency_overrides[get_settings]=lambda:live
    try:
        login(client,user_a)
        case=Case(organization_id=org_a.id,case_reference='LIVE-CONNECTOR-UNIT-TEST',title='Mocked provider test only',data_mode=DataMode.LIVE,created_by=user_a.id)
        db.add(case);db.flush()
        network=Network(key='base',display_name='Base',family=NetworkFamily.account,chain_id=8453,native_asset_symbol='ETH',is_supported=True)
        db.add(network);db.flush()
        from app.services.cctp.provenance import get_usdc_contract
        asset=Asset(network_id=network.id,kind=AssetKind.token,token_contract=get_usdc_contract('base'),decimals=6,
            display_symbol='USDC',is_supported=True,data_mode=DataMode.LIVE)
        db.add(asset);db.flush()
        async def checked(*args,**kwargs):return {'result':verify_components(evidence,data_mode='LIVE'),'evidence':evidence,'acquisitions':[]}
        monkeypatch.setattr('app.services.operations.cctp.acquire',checked)
        base=f'/api/v1/cases/{case.id}/cross-chain'
        created=client.post(base+'/cctp',json={'source_tx_hash':evidence['source_tx_hash']})
        assert created.status_code==201,created.text
        review=created.json()['data'];assert review['status']=='matched_finalized_provider_evidence'
        continued=client.post(base+'/'+review['id']+'/continue')
        assert continued.status_code==202,continued.text
        job=continued.json()['data'];again=client.post(base+'/'+review['id']+'/continue').json()['data']
        assert again['id']==job['id']
        import uuid
        saved_job=db.get(InvestigationJob,uuid.UUID(job['id']))
        assert saved_job.input_payload['token_contract']==get_usdc_contract('base')
        assert saved_job.input_payload['mode']=='address_discovery' and saved_job.input_payload['seed_event_reference'] is None
        login(client,user_b)
        assert client.get(base).status_code==404
        assert client.get(base+'/'+review['id']+'/evidence').status_code==404
        login(client,user_a)
        saved=db.get(CrossChainReview,uuid.UUID(review['id']));saved.bundle_sha256='0'*64;db.flush()
        assert client.get(base+'/'+review['id']+'/evidence').status_code==409
    finally:
        client.app.dependency_overrides.pop(get_settings,None)
