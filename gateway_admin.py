#!/usr/bin/env python3
"""Local administrator-only credential issuance. Tokens are hashed at rest.
This tool does not establish a connection to any government platform.
"""
from __future__ import annotations
import argparse
import datetime as dt
import os
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    issue=sub.add_parser('issue');issue.add_argument('--organization-slug',required=True)
    issue.add_argument('--name',required=True)
    issue.add_argument('--source',choices=['agency_gateway','ncrp_gateway','sahyog_gateway','vasp_gateway'],default='agency_gateway')
    issue.add_argument('--days',type=int,default=30)
    revoke=sub.add_parser('revoke');revoke.add_argument('--id',type=uuid.UUID,required=True)
    ls=sub.add_parser('list');ls.add_argument('--organization-slug',required=True)
    a=p.parse_args();os.chdir(ROOT/'api');sys.path.insert(0,str(ROOT/'api'))
    from sqlalchemy import select
    from app.db.base import SessionLocal
    from app.models.identity import Organization
    from app.models.operations import IntakeCredential
    from app.models.casework import AuditEvent
    from app.services.operations.intake import issue_credential
    with SessionLocal() as db:
        if a.command=='revoke':
            row=db.get(IntakeCredential,a.id)
            if not row: p.error('Credential not found.')
            row.is_active=False
            db.add(AuditEvent(organization_id=row.organization_id,action='intake.credential_revoked',
                object_type='intake_credential',object_id=str(row.id),request_id='local-admin',audit_metadata={}))
            db.commit();print('Revoked.');return
        org=db.scalar(select(Organization).where(Organization.slug==a.organization_slug))
        if not org: p.error('Organization not found. Use manage.py create-operator first.')
        if a.command=='list':
            for row in db.scalars(select(IntakeCredential).where(IntakeCredential.organization_id==org.id)):
                print(row.id,row.name,row.source,'active='+str(row.is_active),'expires='+row.expires_at.isoformat())
            return
        row,token=issue_credential(db,organization_id=org.id,name=a.name,source=a.source,days=a.days)
        db.add(AuditEvent(organization_id=org.id,action='intake.credential_issued',object_type='intake_credential',
            object_id=str(row.id),request_id='local-admin',audit_metadata={'source':row.source,'expires_at':row.expires_at.isoformat()}))
        db.commit()
        print('Credential ID:',row.id,'\nExpires:',row.expires_at.isoformat())
        print('Store this one-time token in your gateway secret manager. Do not share it in screenshots or reports.')
        print(token)
        print('This is an application-owned contract. Official platform onboarding/mapping remains required.')

if __name__=='__main__': main()
