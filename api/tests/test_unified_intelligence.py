"""Regression examples for the safety-critical TraceCrypt feature ports."""
import copy
import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
import pytest
from app.adapters.base import ExecutionVerification, Direction, TransferPage
from app.adapters.receipt_gate import ReceiptGateAdapter
from app.engine.tracer import ChronologicalTracer
from app.models.enums import ExecutionStatus, ConfirmationState, CaseFlowLinkage
from app.services.tracecrypt_intelligence import analyze_trace, correlate_traces, verified_events, trace_digest
from app.core.base58codec import b58encode, b58decode
from tests.test_tracer import ScriptedAdapter, transfer, settings, registry, ASSET, A, B, C, CUTOFF


def event(ref, frm='A', to='B', amount='100', minute=0, **extra):
    return {'event_reference':ref,'tx_hash':ref,'from_address':frm,'to_address':to,
        'amount_base_units':amount,'execution_status':'success','confirmation_state':'confirmed',
        'block_time':(dt.datetime(2026,8,1,tzinfo=dt.UTC)+dt.timedelta(minutes=minute)).isoformat(),
        'asset':{'token_contract':'token1','decimals':6}, **extra}


def trace(*rows, network='tron', mode='SYNTHETIC', endings=None):
    return {'seed':{'network_key':network},'scope':{'data_mode':mode,'coverage_status':'complete_within_scope'},
        'observed_transfers':list(rows),'branch_endings':endings or []}


def rules(t):
    return {p['rule'] for p in analyze_trace(t)['patterns']}


@pytest.mark.parametrize('raw',[b'',b'\x00',b'\x00\x00abc',bytes(range(256)),b'hello world'])
def test_base58_exact_roundtrip(raw):
    assert b58decode(b58encode(raw)) == raw


@pytest.mark.parametrize('bad',['0','O','I','l','é'])
def test_base58_rejects_non_alphabet(bad):
    with pytest.raises((ValueError,UnicodeError)):
        b58decode(bad)


@pytest.mark.parametrize('status,finality',[(ExecutionStatus.unknown,ConfirmationState.unknown),
    (ExecutionStatus.success,ConfirmationState.provisional),(ExecutionStatus.failed,ConfirmationState.confirmed),
    (ExecutionStatus.success,ConfirmationState.removed)])
async def test_unverified_seed_does_not_start_at_recipient(status, finality):
    seed=transfer('seed',A,B,100,1,execution=status,confirmation=finality)
    adapter=ScriptedAdapter([transfer('onward',B,C,90,2)])
    result=await ChronologicalTracer(adapter,registry(),settings()).trace(
        seed_address=A,asset=ASSET,analysis_cutoff=CUTOFF,seed_event=seed)
    assert adapter.calls == []
    assert result.case_flow_linkage is CaseFlowLinkage.not_established
    assert any(l.code=='seed_not_verified' for l in result.limitations)


@pytest.mark.parametrize('amount',[0,-1,-100])
def test_nonpositive_cannot_extend(amount):
    assert not ChronologicalTracer._is_spendable(transfer('a',A,B,amount,1))


async def test_unknown_successor_is_an_explicit_gap():
    seed=transfer('seed',A,B,100,1)
    unknown=transfer('next',B,C,90,2,execution=ExecutionStatus.unknown)
    adapter=ScriptedAdapter([unknown])
    result=await ChronologicalTracer(adapter,registry(),settings()).trace(
        seed_address=A,asset=ASSET,analysis_cutoff=CUTOFF,seed_event=seed)
    assert C not in adapter.calls
    assert any(l.code=='execution_or_finality_unverified' for l in result.limitations)


class VerifyingAdapter(ScriptedAdapter):
    def __init__(self, events):
        super().__init__(events); self.verify_calls=0
    async def verify_execution(self, events):
        self.verify_calls+=1
        return ExecutionVerification(events=[replace(e,execution_status=ExecutionStatus.success,
            confirmation_state=ConfirmationState.confirmed) for e in events], receipts={},unverified=[])


async def test_gate_checks_before_path_and_caches_one_run():
    delegate=VerifyingAdapter([transfer('e',A,B,100,1,execution=ExecutionStatus.unknown)])
    gate=ReceiptGateAdapter(delegate)
    params=dict(address=A,asset=ASSET,direction=Direction.outgoing,analysis_cutoff=CUTOFF)
    cheap=await gate.fetch_transfers(**params,enrich=False)
    assert cheap.events[0].execution_status is ExecutionStatus.unknown
    assert delegate.verify_calls == 0
    full=await gate.fetch_transfers(**params)
    assert ChronologicalTracer._is_spendable(full.events[0])
    await gate.fetch_transfers(**params)
    assert delegate.verify_calls == 1


async def test_gate_does_not_resurrect_removed_inclusion():
    delegate=VerifyingAdapter([transfer('e',A,B,100,1,confirmation=ConfirmationState.removed)])
    page=await ReceiptGateAdapter(delegate).fetch_transfers(address=A,asset=ASSET,
        direction=Direction.outgoing,analysis_cutoff=CUTOFF)
    assert page.events[0].confirmation_state is ConfirmationState.removed
    assert delegate.verify_calls == 0


def test_pattern_does_not_claim_sender_owned_by_exchange():
    ending={'address':'EXCHANGE','endpoint_class':'known_service','attribution_status':'supported',
        'arrival_event_reference':'out','branch_path':['in','out'],'hop_depth':1,
        'label':{'review_state':'accepted','entity_name':'Reviewed example','address_role':'unknown'}}
    out=analyze_trace(trace(event('in','victim','fraudster','100',0),
        event('out','fraudster','EXCHANGE','90',1),endings=[ending]))
    assert 'rapid_forwarding' in out['risk']['rules_triggered']
    assert out['service_boundaries'][0]['sender_service_control']=='not_inferred'
    assert not out['service_boundaries'][0]['direct_deposit_role_verified']
    assert out['risk']['trained_model'] is False
    assert out['allocation'].startswith('unknown')


@pytest.mark.parametrize('bad',['provisional','unknown','removed'])
def test_finality_unverified_never_flagged(bad):
    out=analyze_trace(trace(event('a',confirmation_state=bad)))
    assert out['graph_metrics']['transfer_count'] == 0


@pytest.mark.parametrize('amount',[1.5,True,'-1','NaN','1e6',str(2**256)])
def test_invalid_amount_not_silently_coerced(amount):
    assert verified_events(trace(event('a',amount=amount)))[0] == []


def test_uint256_exact_and_no_double_counting():
    big=str(2**200+173)
    e=event('a',amount=big)
    out=analyze_trace(trace(e,copy.deepcopy(e)))
    assert out['graph_metrics']['transfer_count']==1
    assert out['observed_volume'][0]['gross_edge_base_units']==big


def test_conflicting_identity_excluded():
    assert verified_events(trace(event('a'),event('a',amount='99')))[0] == []


def test_parallel_transactions_preserved():
    out=analyze_trace(trace(event('a'),event('b')))
    assert out['graph_metrics']['transfer_count']==2
    assert out['graph_metrics']['unique_directed_pairs']==1


def test_fan_out_requires_distinct_recipients():
    assert 'fan_out' not in rules(trace(*[event(str(i)) for i in range(4)]))
    assert 'fan_out' in rules(trace(*[event(str(i),to=str(i)) for i in range(3)]))


@pytest.mark.parametrize('time',['2026-08-01T00:00:00',None,'bad','2026-07-31T23:00:00Z'])
def test_bad_or_earlier_timestamp_not_rapid_forwarding(time):
    assert 'rapid_forwarding' not in rules(trace(event('in'),event('out','B','C',minute=1,block_time=time)))


def test_unlike_assets_not_matched_or_added():
    t=trace(event('in'),event('out','B','C',minute=1,asset={'token_contract':'other','decimals':6}))
    assert 'rapid_forwarding' not in rules(t)
    assert len(analyze_trace(t)['observed_volume']) == 2


def test_does_not_modify_trace():
    t=trace(event('a')); before=copy.deepcopy(t)
    out=analyze_trace(t)
    assert t==before and out['input_trace_sha256']==trace_digest(t)


def test_cycle_is_topology_not_laundering_proof():
    out=analyze_trace(trace(event('a','A','B'),event('b','B','A',minute=1)))
    assert out['graph_metrics']['has_directed_cycle']
    assert 'not proof' in out['disclaimer']


def test_unverified_service_arrival_never_supported_boundary():
    t=trace(event('a',confirmation_state='unknown'),endings=[{'address':'B','endpoint_class':'known_service',
        'attribution_status':'supported','arrival_event_reference':'a','branch_path':['a'],
        'label':{'review_state':'accepted'}}])
    assert analyze_trace(t)['service_boundaries']==[]


def test_cross_case_excludes_service_and_deduplicates_case_runs():
    t=trace(event('a','same','exchange'),endings=[{'address':'exchange','endpoint_class':'known_service'}])
    rows=[{'case_id':'1','trace':t},{'case_id':'1','trace':t},{'case_id':'2','trace':t}]
    links=correlate_traces(rows)
    assert [x['shared_address'] for x in links]==['same']
    assert links[0]['case_count']==2 and links[0]['common_control']=='not_established'
    assert correlate_traces(rows[:2])==[]


@pytest.mark.parametrize('network,mode',[('ethereum','SYNTHETIC'),('tron','LIVE')])
def test_cross_case_never_combines_network_or_mode(network,mode):
    assert correlate_traces([{'case_id':'1','trace':trace(event('a'))},
        {'case_id':'2','trace':trace(event('a'),network=network,mode=mode)}]) == []


def test_csv_formula_text_neutralized_not_authoritative_json():
    import csv,io
    from app.services.evidence_export import _csv_bytes
    parsed=list(csv.reader(io.StringIO(_csv_bytes(['a','b'],[['=SUM(1,2)','123']]).decode())))
    assert parsed[1]==["'=SUM(1,2)",'123']


@pytest.mark.parametrize('budget',[1,3])
async def test_empty_nonterminal_pages_never_become_complete_empty_history(budget):
    from app.engine.tracer import Budgets
    class NonterminalAdapter(ScriptedAdapter):
        async def fetch_transfers(self,**kwargs):
            return TransferPage(events=[],next_cursor='stuck')
    a=NonterminalAdapter([])
    result=await ChronologicalTracer(a,registry(),settings(),budgets=Budgets(
        max_hops=8,max_events=100,max_provider_requests=budget,wall_clock_seconds=30)).trace(
        seed_address=A,asset=ASSET,analysis_cutoff=CUTOFF,seed_event=transfer('seed',A,B,100,1))
    assert result.coverage_status.value != 'complete_within_scope'
    assert any(l.code in ('provider_budget_exhausted','provider_parse_error') for l in result.limitations)
