#!/usr/bin/env python3
"""Local launcher. Never installs packages or substitutes synthetic data for LIVE."""
from __future__ import annotations
import argparse
import importlib.util
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Apply migrations; seed only in local SYNTHETIC mode.')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare and exit without starting HTTP.')
    parser.add_argument('--with-worker', action='store_true', help='Start a companion queue worker; stop it when the server exits.')
    parser.add_argument('--port', type=int, default=8010)
    parser.add_argument('--host', default='127.0.0.1', help='Keep localhost for the demonstration.')
    args = parser.parse_args()
    if not ((3, 12) <= sys.version_info[:2] < (3, 14)):
        parser.error('Use Python 3.12 or 3.13.')
    missing = [m for m in ('fastapi','uvicorn','sqlalchemy','alembic','argon2','httpx','pydantic_settings')
               if importlib.util.find_spec(m) is None]
    if missing:
        print('Missing packages: '+', '.join(missing), file=sys.stderr)
        print('Install first: python -m pip install -r requirements-runtime.txt', file=sys.stderr)
        return 2
    (ROOT/'var').mkdir(exist_ok=True)
    envfile = ROOT/'api'/'.env'
    if not envfile.exists():
        # Configuration is generated on the user's own machine, never packaged.
        with envfile.open('x', encoding='utf-8') as f:
            f.write('CFA_APP_ENV=dev\nCFA_DATA_MODE=SYNTHETIC\n'
                    'CFA_SECRET_KEY='+secrets.token_urlsafe(48)+'\n'
                    'CFA_DATABASE_URL=sqlite+pysqlite:///../var/unified.db\n'
                    'CFA_ENGINE_VERSION=unified-2.0\n')
        try:
            envfile.chmod(0o600)
        except OSError:
            pass
    os.chdir(ROOT/'api')
    sys.path.insert(0, str(ROOT/'api'))
    from app.core.settings import get_settings, DataMode, AppEnv
    settings = get_settings()
    if settings.app_env is AppEnv.prod:
        parser.error('Production requires your reviewed deployment configuration; this local launcher is not a production installer.')
    if args.prepare or args.prepare_only:
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'], check=True)
        if settings.data_mode is DataMode.SYNTHETIC:
            subprocess.run([sys.executable,str(ROOT/'scripts'/'seed_demo.py')], check=True)
        else:
            print('No synthetic seed loaded. Create an operator and register supported assets explicitly.')
    else:
        from sqlalchemy import inspect
        from app.db.base import engine
        if not all(inspect(engine).has_table(name) for name in ('investigation_jobs','cross_chain_reviews')):
            parser.error('Database not prepared: run python launch.py --prepare first.')
    if args.prepare_only:
        return 0
    print(f'\nTraceCrypt Unified: http://{args.host}:{args.port}/workspace/\n'
          f'Mode: {settings.data_mode.value}. No external submission or asset-freezing connection.\n', flush=True)
    import uvicorn
    worker = subprocess.Popen([sys.executable, str(ROOT/'operations_worker.py')]) if args.with_worker else None
    try:
        uvicorn.run('app.main:app', host=args.host, port=args.port, reload=False)
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill(); worker.wait()
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f'Launch failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
