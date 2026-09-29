"""Opt-in, held-out anomaly ranking of comparable saved investigation graphs.

No labels are generated. No model is loaded from pickle. Scores measure only
unusual graph statistics relative to this organization's complaint-derived
cohort; they are NOT probabilities of fraud, ownership, or recoverability.
"""
from __future__ import annotations
import datetime as dt
import math
from collections import Counter
from typing import Any
from app.services.tracecrypt_intelligence import trace_digest, verified_events

FEATURES = ["log_verified_transfers", "log_distinct_addresses", "log_max_in_degree",
            "log_max_out_degree", "repeated_pair_fraction", "self_transfer_fraction"]


def feature_vector(trace: dict[str, Any]) -> list[float] | None:
    events, excluded = verified_events(trace)
    if not events or excluded.get("conflicting_event_identity") or excluded.get("execution_or_finality_unverified"):
        return None
    incoming: dict[str, set[str]] = {}; outgoing: dict[str, set[str]] = {}
    pairs=Counter((e['from_address'],e['to_address']) for e in events)
    for src,dst in pairs:
        incoming.setdefault(dst,set()).add(src); outgoing.setdefault(src,set()).add(dst)
    return [math.log1p(len(events)), math.log1p(len(set(incoming)|set(outgoing))),
        math.log1p(max(map(len,incoming.values()),default=0)), math.log1p(max(map(len,outgoing.values()),default=0)),
        sum(n-1 for n in pairs.values())/len(events), sum(n for (a,b),n in pairs.items() if a==b)/len(events)]


def rank_cohort(records: list[dict[str, Any]], *, network_key: str, token_contract: str,
                data_mode: str, maximum_records: int=500) -> dict[str, Any]:
    base={"method":"IsolationForest", "version":"graph-cohort-v1", "features":FEATURES,
        "network_key":network_key,"token_contract":token_contract,"data_mode":data_mode,
        "scope":"Organization-scoped complaint investigations; not a representative blockchain population.",
        "limitations":["An anomaly is not evidence of fraud, common ownership or funds recoverability.",
            "No adjudicated fraud labels are available here; fraud accuracy, recall and calibration are not measured.",
            "Different tracing windows and graph boundaries can cause differences in these features.",
            "Only one earliest complete saved trace per seed wallet is used. Training and scored seed wallets are disjoint.",
            "Training uses the earlier 80% by saved time; only the later 20% is scored. Scores do not modify evidence or labels.",
            "This optional bounded endpoint refits on demand; it is not a production model lifecycle service."]}
    skipped=Counter(); eligible=[]
    for r in sorted(records,key=lambda row:(row.get('created_at',''),row.get('run_id','')))[:maximum_records]:
        trace=r.get('trace') or {}; seed=trace.get('seed') or {}; scope=trace.get('scope') or {}
        if (seed.get('network_key')!=network_key or (seed.get('asset') or {}).get('token_contract')!=token_contract
                or scope.get('data_mode')!=data_mode):
            skipped['different_network_asset_or_mode']+=1; continue
        if trace_digest(trace)!=r.get('trace_sha256'):
            skipped['integrity_failure']+=1; continue
        if scope.get('coverage_status')!='complete_within_scope':
            skipped['incomplete_coverage']+=1; continue
        vector=feature_vector(trace)
        if vector is None or not seed.get('address'):
            skipped['insufficient_verified_data']+=1; continue
        eligible.append((r,vector))
    seen=set(); unique=[]
    for r,vector in eligible:
        address=r['trace']['seed']['address']
        if address in seen:
            skipped['repeated_seed_wallet']+=1; continue
        seen.add(address); unique.append((r,vector))
    base.update(eligible_unique_wallets=len(unique),excluded=dict(skipped),minimum_unique_wallets=25)
    if len(unique)<25:
        return {**base,"status":"insufficient_data","training_count":0,"scored_count":0,"rankings":[]}
    split=int(len(unique)*.8); training=unique[:split]; testing=unique[split:]
    # Do not accept temporal ties across the split: their order cannot be established.
    cutoff=training[-1][0]['created_at']
    testing=[pair for pair in testing if pair[0]['created_at']>cutoff]
    if not testing:
        return {**base,"status":"insufficient_temporal_separation","training_count":len(training),"scored_count":0,"rankings":[]}
    try:
        import sklearn
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return {**base,"status":"dependency_unavailable","training_count":0,"scored_count":0,"rankings":[]}
    model=IsolationForest(n_estimators=64,random_state=42,contamination='auto',n_jobs=1)
    model.fit([v for _,v in training])
    scores=-model.score_samples([v for _,v in testing])
    ranking=[{"run_id":r['run_id'],"case_id":r['case_id'],"seed_wallet":r['trace']['seed']['address'],
        "saved_at":r['created_at'],"trace_sha256":r['trace_sha256'],"anomaly_score":round(float(score),8),
        "interpretation":"Higher means more unusual in this cohort, not more likely criminal.","features":dict(zip(FEATURES,v))}
        for (r,v),score in zip(testing,scores,strict=True)]
    ranking.sort(key=lambda row:(-row['anomaly_score'],row['run_id']))
    return {**base,"status":"ranked_held_out_graphs","training_count":len(training),"scored_count":len(testing),
        "train_saved_time_cutoff":cutoff,"sklearn_version":sklearn.__version__,"random_state":42,"n_estimators":64,
        "training_trace_hashes":[r['trace_sha256'] for r,_ in training],"rankings":ranking}
