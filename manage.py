#!/usr/bin/env python3
"""Explicit operator setup and foreground watch polling. No external submissions."""
from __future__ import annotations
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parent


def arguments():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    user=sub.add_parser('create-operator',help='Create a new local account; password prompted, never stored in arguments.')
    user.add_argument('--email',required=True)
    user.add_argument('--organization',required=True)
    user.add_argument('--slug',required=True)
    asset=sub.add_parser('register-token',help='Register explicit operator-sourced token metadata, not an issuer/ownership assertion.')
    asset.add_argument('--network',choices=['tron','ethereum','bsc','base'],required=True)
    asset.add_argument('--contract',required=True)
    asset.add_argument('--decimals',type=int,required=True)
    asset.add_argument('--symbol',required=True)
    asset.add_argument('--source',required=True,help='Reviewed issuer/chain source reference. No source is invented.')
    asset.add_argument('--verify-evm',action='store_true',help='Call the configured RPC to check chain, bytecode and decimals before registration.')
    poll=sub.add_parser('poll-watches',help='Poll enabled watches serially, once or in a visible foreground loop. One worker per database.')
    poll.add_argument('--interval',type=int,default=0,help='0 means once; otherwise repeat every >=30 seconds until Ctrl+C.')
    poll.add_argument('--watch-id',action='append',type=uuid.UUID)
    return p,p.parse_args()


async def do_polls(settings,args):
    from sqlalchemy import select
    from app.db.base import SessionLocal
    from app.models.casework import Watch
    from app.models.chain import Network
    from app.services.monitoring import poll_watch
    from app.services.trace_service import build_adapter
    if args.interval and args.interval<30:
        raise ValueError('Interval must be 0 (once) or at least 30 seconds.')
    while True:
        with SessionLocal() as db:
            q=select(Watch).where(Watch.is_active.is_(True),Watch.data_mode==settings.data_mode)
            if args.watch_id:
                q=q.where(Watch.id.in_(args.watch_id))
            watches=db.execute(q).scalars().all()
            for watch in watches:
                try:
                    network=db.get(Network,watch.network_id)
                    adapter=build_adapter(settings,network_key=network.key)
                    result=await asyncio.wait_for(poll_watch(db,watch,adapter,
                        observation_mode=settings.data_mode,max_pages=settings.monitor_max_pages,
                        secrets=(settings.tron_api_key,settings.ethereum_rpc_url,settings.bsc_rpc_url,settings.base_rpc_url)),
                        settings.budget_wall_clock_seconds+10)
                    db.commit()
                    # Local operator terminal only; output includes case-associated event references.
                    print(json.dumps(result.to_json()),flush=True)
                except Exception as exc:
                    db.rollback()
                    from app.services.monitoring import redact
                    print(json.dumps({'watch_id':str(watch.id),'error':redact(str(exc),(
                        settings.tron_api_key,settings.ethereum_rpc_url,settings.bsc_rpc_url,settings.base_rpc_url))}),file=sys.stderr,flush=True)
            if not watches:
                print('No enabled watches in the configured data mode.',flush=True)
        if not args.interval:
            break
        await asyncio.sleep(args.interval)


def main():
    parser,args=arguments()
    os.chdir(ROOT/'api');sys.path.insert(0,str(ROOT/'api'))
    from sqlalchemy import select
    from app.core.settings import get_settings,DataMode
    from app.db.base import SessionLocal
    settings=get_settings()
    if args.command=='poll-watches':
        asyncio.run(do_polls(settings,args));return
    with SessionLocal() as db:
        if args.command=='create-operator':
            from app.models.identity import User,Organization,Membership
            from app.core.security import hash_password
            if '@' not in args.email or len(args.email)>320:
                parser.error('A valid account email is required.')
            if db.execute(select(User).where(User.email==args.email)).scalar_one_or_none():
                parser.error('Account already exists; refusing to overwrite its password or memberships.')
            password=getpass.getpass('New account password (at least 14 characters): ')
            if len(password)<14 or password!=getpass.getpass('Repeat password: '):
                parser.error('Passwords must match and contain at least 14 characters.')
            org=db.execute(select(Organization).where(Organization.slug==args.slug)).scalar_one_or_none()
            if not org:
                org=Organization(name=args.organization,slug=args.slug);db.add(org);db.flush()
            user=User(email=args.email,display_name=args.email.split('@')[0],password_hash=hash_password(password))
            db.add(user);db.flush();db.add(Membership(user_id=user.id,organization_id=org.id,role='investigator'))
            db.commit();print('Created operator account. No demonstration password was used.');return
        from app.models.chain import Network,Asset
        from app.models.enums import AssetKind,NetworkFamily
        from app.services.addresses import canonicalize
        from app.adapters.evm import EVM_NETWORKS
        if not 0<=args.decimals<=255 or not 1<=len(args.symbol)<=40:
            parser.error('Decimals must be 0..255 and display symbol 1..40 characters.')
        contract=canonicalize(args.network,args.contract).canonical
        if args.verify_evm:
            if args.network not in EVM_NETWORKS or settings.data_mode is not DataMode.LIVE:
                parser.error('--verify-evm requires an EVM network and CFA_DATA_MODE=LIVE.')
            from app.services.trace_service import build_adapter
            facts=asyncio.run(build_adapter(settings,network_key=args.network).verify_token_contract(contract))
            if not facts['code_present'] or facts['decimals']!=args.decimals:
                parser.error('RPC bytecode/decimals checks failed; asset not registered.')
            print(json.dumps(facts,indent=2))
        spec=EVM_NETWORKS.get(args.network)
        network=db.execute(select(Network).where(Network.key==args.network)).scalar_one_or_none()
        if not network:
            network=Network(key=args.network,display_name=spec.display_name if spec else 'TRON mainnet',
                family=NetworkFamily.account,chain_id=spec.chain_id if spec else None,
                native_asset_symbol=spec.native_symbol if spec else 'TRX',is_supported=True)
            db.add(network);db.flush()
        existing=db.execute(select(Asset).where(Asset.network_id==network.id,
            Asset.kind==AssetKind.token,Asset.token_contract==contract)).scalar_one_or_none()
        if existing:
            parser.error('Asset already exists; refusing to overwrite metadata or mix its data mode. Use a separate database for LIVE.')
        db.add(Asset(network_id=network.id,kind=AssetKind.token,token_contract=contract,
            decimals=args.decimals,display_symbol=args.symbol,issuer_reference=args.source,
            verified_at=None,is_supported=True,data_mode=settings.data_mode))
        db.commit()
        print('Registered operator-sourced metadata. verified_at remains unset: this is not independent issuer verification.')

if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nPolling stopped. Committed checkpoints remain saved.')
    except Exception as exc:
        # Avoid echoing a provider URL, database URL or password through an exception.
        print(f'Operation failed ({type(exc).__name__}); check configuration and credentials locally.',file=sys.stderr)
        raise SystemExit(1)
