#!/usr/bin/env python3
"""Submit application-owned intake; never print the bearer token or follow redirects."""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8010')
    parser.add_argument('--file',type=Path,required=True)
    args=parser.parse_args();base=args.base_url.rstrip('/');parts=urlsplit(base)
    if parts.username or parts.password or parts.query or parts.fragment or parts.path:
        parser.error('Use the base server origin without credentials, paths or query strings.')
    if parts.scheme!='https' and not(parts.scheme=='http' and parts.hostname in {'127.0.0.1','localhost','::1'}):
        parser.error('HTTPS is required except on localhost.')
    token=os.environ.get('TRACECRYPT_INTAKE_TOKEN','')
    if not token.startswith('tcu_'):parser.error('Set TRACECRYPT_INTAKE_TOKEN to an issued token in your environment.')
    try:
        content=args.file.read_bytes()
        if len(content)>65536:raise ValueError('Payload exceeds 64 KiB.')
        json.loads(content)
        request=Request(base+'/api/v1/integrations/complaints',data=content,method='POST',
            headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
        with build_opener(NoRedirect).open(request,timeout=30) as response:
            body=json.load(response)
        print(json.dumps(body,indent=2));return 0
    except HTTPError as exc:
        print('Intake rejected: HTTP '+str(exc.code)+'. Check schema, credentials or conflicting reference.',file=sys.stderr);return 1
    except (URLError,OSError,ValueError) as exc:
        print('Unable to submit ('+type(exc).__name__+'). Check file, connection and configuration.',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
