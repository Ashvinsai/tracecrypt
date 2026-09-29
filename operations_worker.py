#!/usr/bin/env python3
"""Run the durable trace queue. Use one SQLite worker; PostgreSQL supports claims
with SKIP LOCKED. Optional watch polling must have only one scheduler per DB.
No government/VASP request or blockchain transaction is sent by this worker.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parent


async def main_async(args):
    from sqlalchemy import select
    from app.core.settings import get_settings
    from app.db.base import SessionLocal
    from app.models.casework import Watch
    from app.models.chain import Network
    from app.services.monitoring import poll_watch
    from app.services.operations.queue import process_one
    from app.services.trace_service import build_adapter
    settings=get_settings()
    next_watches=0.0
    while True:
        try:
            with SessionLocal() as db:
                result=await process_one(db, settings)
                if result['status']!='idle':
                    # No addresses, account names, provider URLs or complaint text.
                    print(json.dumps({k:result.get(k) for k in ('id','status','attempts','duration_ms','error_code')}),flush=True)
            if args.poll_watches and time.monotonic()>=next_watches:
                with SessionLocal() as db:
                    identifiers=list(db.scalars(select(Watch.id).where(Watch.is_active.is_(True),
                        Watch.data_mode==settings.data_mode).order_by(Watch.id)).all())
                for ident in identifiers:
                    with SessionLocal() as db:
                        watch=db.get(Watch,ident)
                        if not watch or not watch.is_active: continue
                        try:
                            network=db.get(Network,watch.network_id)
                            outcome=await asyncio.wait_for(poll_watch(db,watch,build_adapter(settings,network_key=network.key),
                                observation_mode=settings.data_mode,max_pages=settings.monitor_max_pages,
                                secrets=(settings.tron_api_key,settings.ethereum_rpc_url,settings.bsc_rpc_url,settings.base_rpc_url)),
                                timeout=settings.budget_wall_clock_seconds+10)
                            db.commit()
                            print(json.dumps({'watch_id':str(ident),'poll_status':outcome.to_json().get('status'),
                                              'new_alerts':outcome.to_json().get('new_alerts')}),flush=True)
                        except Exception as exc:
                            db.rollback()
                            print(json.dumps({'watch_id':str(ident),'error_class':type(exc).__name__}),flush=True)
                next_watches=time.monotonic()+args.watch_interval
        except Exception as exc:
            # Database startup/race errors do not kill the entire worker. Work
            # interrupted after claim is recoverable after its lease expires.
            print(json.dumps({'worker_error_class':type(exc).__name__}),file=sys.stderr,flush=True)
            if args.once: return 1
        if args.once: return 0
        await asyncio.sleep(args.interval)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true',help='Process at most one ready trace job and exit.')
    parser.add_argument('--interval',type=float,default=3.0)
    parser.add_argument('--poll-watches',action='store_true',help='Only one watch scheduler per database; do not manually poll concurrently.')
    parser.add_argument('--watch-interval',type=int,default=60)
    args=parser.parse_args()
    if not 1<=args.interval<=300 or args.watch_interval<30:
        parser.error('Queue interval must be 1..300 seconds; watch interval must be at least 30 seconds.')
    os.chdir(ROOT/'api');sys.path.insert(0,str(ROOT/'api'))
    try: return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print('Worker stopped. Leased unfinished jobs can be recovered by the next worker.',flush=True)
        return 0

if __name__=='__main__': raise SystemExit(main())
