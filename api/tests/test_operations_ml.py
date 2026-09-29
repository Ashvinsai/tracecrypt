"""Synthetic model cohorts; no production labels or fraud-accuracy claims."""
import copy
from app.services.operations.ml import rank_cohort, feature_vector
from app.services.tracecrypt_intelligence import trace_digest
from tests.conftest import login
from tests.test_trace_endpoint import SUPPORTED_CONTRACT


def cohort(n=30):
    rows=[]
    for i in range(n):
        asset={'token_contract':'token','decimals':6};address=f'SYNTHETIC-wallet-{i}'
        trace={'seed':{'address':address,'network_key':'tron','asset':asset},
            'scope':{'data_mode':'SYNTHETIC','coverage_status':'complete_within_scope'},
            'observed_transfers':[{'event_reference':f'SYNTHETIC-event-{i}-{j}',
                'tx_hash':f'SYNTHETIC-tx-{i}-{j}','from_address':address,'to_address':f'SYNTHETIC-target-{j}',
                'amount_base_units':'1000000','asset':asset,'execution_status':'success','confirmation_state':'confirmed'}
                for j in range(1+(i%7))]}
        rows.append({'trace':trace,'trace_sha256':trace_digest(trace),'run_id':str(i),'case_id':str(i),
            'created_at':f'2026-09-{i+1:02d}T00:00:00+00:00'})
    return rows


def ranked(rows):return rank_cohort(rows,network_key='tron',token_contract='token',data_mode='SYNTHETIC')


def test_actual_model_scores_only_later_disjoint_graphs():
    rows=cohort(); result=ranked(rows)
    assert result['status']=='ranked_held_out_graphs'
    assert result['training_count']==24 and result['scored_count']==6
    assert set(result['training_trace_hashes']).isdisjoint({r['trace_sha256'] for r in result['rankings']})
    assert all(r['saved_at']>result['train_saved_time_cutoff'] for r in result['rankings'])
    assert result['rankings']==ranked(rows)['rankings']
    assert not any('probability' in r for r in result['rankings'])


def test_insufficient_data_not_fake_scores():
    result=ranked(cohort(2));assert result['status']=='insufficient_data' and not result['rankings']


def test_mixed_modes_bad_hash_and_duplicate_seeds_excluded():
    rows=cohort(30);rows[0]['trace']['scope']['data_mode']='LIVE'
    rows[1]['trace_sha256']='bad'
    rows[2]['trace']['scope']['coverage_status']='failed';rows[2]['trace_sha256']=trace_digest(rows[2]['trace'])
    rows[4]['trace']['seed']['address']=rows[3]['trace']['seed']['address'];rows[4]['trace_sha256']=trace_digest(rows[4]['trace'])
    result=ranked(rows)
    assert result['eligible_unique_wallets']==26
    assert result['excluded']=={'different_network_asset_or_mode':1,'integrity_failure':1,'incomplete_coverage':1,'repeated_seed_wallet':1}


def test_no_chronological_separation_produces_no_holdout_scores():
    rows=cohort()
    for row in rows:row['created_at']='2026-09-01T00:00:00+00:00'
    assert ranked(rows)['status']=='insufficient_temporal_separation'


def test_model_api_requires_session_and_is_empty_for_empty_org(client,user_a,synthetic_usdt):
    path=f'/api/v1/operations/ml-ranking?network_key=tron&token_contract={SUPPORTED_CONTRACT}'
    assert client.get(path).status_code==401
    login(client,user_a);result=client.get(path)
    assert result.status_code==200,result.text
    assert result.json()['data']['status']=='insufficient_data'
    assert result.json()['data']['token_contract']==SUPPORTED_CONTRACT


def test_model_api_uses_persisted_same_tenant_token_cohort(client,db,user_a,user_b,org_a,synthetic_usdt):
    import datetime as dt
    from app.core.settings import DataMode
    from app.models.casework import Case
    from app.models.unified import InvestigationSnapshot
    for i, record in enumerate(cohort()):
        trace=record['trace']
        trace['seed']['asset']['token_contract']=SUPPORTED_CONTRACT
        case=Case(organization_id=org_a.id,created_by=user_a.id,
            case_reference=f'SYNTHETIC-ML-{i}',title='Synthetic ML test fixture',data_mode=DataMode.SYNTHETIC)
        db.add(case);db.flush()
        db.add(InvestigationSnapshot(case_id=case.id,created_by=user_a.id,data_mode='SYNTHETIC',
            created_at=dt.datetime.fromisoformat(record['created_at']),input_payload={},trace=trace,
            intelligence={},trace_sha256=trace_digest(trace),intelligence_sha256=trace_digest({}),request_id='synthetic-test'))
    db.flush()
    path=f'/api/v1/operations/ml-ranking?network_key=tron&token_contract={SUPPORTED_CONTRACT}'
    login(client,user_a)
    response=client.get(path);assert response.status_code==200,response.text
    data=response.json()['data']
    assert data['status']=='ranked_held_out_graphs' and data['scored_count']==6
    assert data['token_contract']==SUPPORTED_CONTRACT
    login(client,user_b)
    assert client.get(path).json()['data']['eligible_unique_wallets']==0
