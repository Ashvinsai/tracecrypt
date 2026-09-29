"""Fail-closed Ethereum -> Base USDC CCTP V2 evidence verification.

This is a narrow protocol connector, not a generic bridge or mixer deanonymizer.
Canonical/finalized status is corroborated through the configured RPC provider;
this process is not itself a consensus light client and does not verify Circle
ECDSA signatures independently. Multi-message receipts remain unresolved.
"""
from __future__ import annotations
import asyncio
import datetime as dt
import re
from dataclasses import asdict
from typing import Any
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.services.cctp.binary import decode_message_v2, decode_burn_message_v2, keccak256
from app.services.cctp.source import extract_cctp_source_messages, MESSAGE_SENT_TOPIC, DEPOSIT_FOR_BURN_V2_TOPIC
from app.services.cctp.destination import (decode_destination_execution, MESSAGE_RECEIVED_V2_TOPIC,
    MINT_AND_WITHDRAW_V2_TOPIC, MINT_AND_WITHDRAW_LEGACY_TOPIC)
from app.services.cctp.client import CircleCctpClient
from app.services.cctp.provenance import get_cctp_contract, get_usdc_contract
from app.adapters.evm import TRANSFER_TOPIC
from app.services.tracecrypt_intelligence import trace_digest

HASH_PATTERN=r'^0x[0-9a-fA-F]{64}$'


class CctpRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    source_tx_hash: str=Field(pattern=HASH_PATTERN)
    destination_tx_hash: str | None=Field(default=None,pattern=HASH_PATTERN)
    destination_from_block: int | None=Field(default=None,ge=0,le=2**63-1)
    destination_to_block: int | None=Field(default=None,ge=0,le=2**63-1)

    @model_validator(mode='after')
    def scope(self):
        a,b=self.destination_from_block,self.destination_to_block
        if (a is None)!=(b is None) or (a is not None and not 0<=b-a<50000):
            raise ValueError('Provide both destination block bounds, ordered, spanning at most 50,000 blocks.')
        self.source_tx_hash=self.source_tx_hash.lower()
        if self.destination_tx_hash:self.destination_tx_hash=self.destination_tx_hash.lower()
        return self


class EvidenceRejected(ValueError):
    """A checkable evidence gap; never reinterpret as a successful empty trace."""


def number(value):
    if isinstance(value,bool) or not isinstance(value,(int,str)):
        raise EvidenceRejected('Only exact integer or quantity strings are accepted.')
    try:return int(value,16) if isinstance(value,str) and value.startswith('0x') else int(value)
    except (ValueError,TypeError,OverflowError) as exc:raise EvidenceRejected('Missing or malformed numeric evidence.') from exc


def require(condition: bool, reason: str):
    if not condition:raise EvidenceRejected(reason)


def matching_logs(receipt,contract,topics):
    return [row for row in receipt.get('logs',[]) if row.get('address','').lower()==contract and
            row.get('topics') and row['topics'][0].lower() in topics]


def verify_receipt(receipt,block,finalized,expected_tx):
    require(isinstance(receipt,dict) and isinstance(block,dict) and isinstance(finalized,dict),'Receipt or block evidence unavailable.')
    require(receipt.get('transactionHash','').lower()==expected_tx.lower(),'Receipt transaction identity mismatch.')
    require(number(receipt.get('status'))==1,'Successful execution is not established.')
    height=number(receipt.get('blockNumber'))
    require(height==number(block.get('number')) and height<=number(finalized.get('number')),'Receipt is not within provider-reported finalized history.')
    require(bool(block.get('hash')) and receipt.get('blockHash')==block['hash'],'Canonical block hash mismatch.')
    require(number(block.get('timestamp'))<=number(finalized.get('timestamp')),'Block timestamps contradict finalized evidence.')
    indices=set()
    for log in receipt.get('logs',[]):
        require(log.get('removed') is False,'Removed or unverified log status.')
        require(log.get('transactionHash','').lower()==expected_tx.lower() and log.get('blockHash')==block['hash']
                and number(log.get('blockNumber'))==height,'Log and receipt identity mismatch.')
        index=number(log.get('logIndex'));require(index not in indices,'Duplicate log identity in receipt.');indices.add(index)
    return dt.datetime.fromtimestamp(number(block['timestamp']),dt.UTC)


def source_message(receipt):
    mts=matching_logs(receipt,get_cctp_contract('ethereum','MessageTransmitterV2'),{MESSAGE_SENT_TOPIC})
    burns=sum((matching_logs(receipt,get_cctp_contract('ethereum',role),{DEPOSIT_FOR_BURN_V2_TOPIC})
               for role in ('TokenMessengerV2','TokenMessengerWithFees')),[])
    require(len(mts)==len(burns)==1,'Exactly one supported source message and burn are required; multiple messages need separate review.')
    messages=extract_cctp_source_messages(receipt)
    require(len(messages)==1,'Source burn and message could not be decoded unambiguously.')
    source=messages[0];header=source.decoded_message;body=source.decoded_burn
    require(header.header_version==body.burn_message_version==1,'Unsupported CCTP wire-format version.')
    require(header.source_domain==0 and header.destination_domain==source.destination_domain==6,'Unsupported source/destination CCTP domains.')
    require(header.sender_address==burns[0]['address'].lower() and header.recipient_address==source.destination_token_messenger
            ==get_cctp_contract('base','TokenMessengerV2'),'TokenMessenger identities do not reconcile.')
    require(source.burn_token==body.burn_token_address==get_usdc_contract('ethereum'),'Source token is not official Ethereum USDC.')
    require(source.amount_base_units==body.amount_base_units>0 and source.mint_recipient==body.mint_recipient_address
        and source.depositor==body.message_sender_address and source.max_fee_base_units==body.max_fee_base_units
        and source.min_finality_threshold==header.min_finality_threshold and source.destination_caller==header.destination_caller,
        'Source message and DepositForBurn immutable fields disagree.')
    return source


def match_api(source,iris):
    if iris.get('sourceTxHash'):
        require(iris['sourceTxHash'].lower()==source.source_tx_hash.lower(),'Iris source transaction mismatch.')
    match=CircleCctpClient.match_source_message(iris,source)
    require(match.matched and not match.ambiguous,'No unique source-linked Iris message was found.')
    require(match.status=='API_REPORTED_COMPLETE' and match.api_message_bytes and match.event_nonce,
            'Iris message is not complete; destination linkage remains unresolved.')
    raw=bytes.fromhex(match.api_message_bytes.removeprefix('0x'))
    original=source.raw_message_bytes
    require(len(raw)==len(original) and len(raw)>=376,'Iris/source message lengths disagree.')
    # Only fields updated by attestation may differ: nonce, executed finality,
    # feeExecuted and expirationBlock. All other raw bytes must match exactly.
    require(raw[:12]==original[:12] and raw[44:144]==original[44:144] and
        raw[148:312]==original[148:312] and raw[376:]==original[376:],
        'Iris message immutable bytes do not match the source-chain message.')
    header=decode_message_v2(raw);body=decode_burn_message_v2(header.message_body)
    require(header.nonce_hex.lower()==match.event_nonce.lower() and any(header.nonce_bytes),'Iris nonce mismatch or zero nonce.')
    require(header.finality_threshold_executed>=header.min_finality_threshold and
        0<=body.fee_executed_base_units<=body.max_fee_base_units<=body.amount_base_units,'Iris fee or finality fields violate message constraints.')
    return match,header,body


def verify_components(evidence: dict[str,Any], *, data_mode: str) -> dict[str,Any]:
    """Pure replayable checks. Live acquisition separately verifies both chain IDs."""
    require(number(evidence.get('ethereum_chain_id'))==1 and number(evidence.get('base_chain_id'))==8453,'RPC chain identity mismatch.')
    src=evidence['source_receipt'];dst=evidence['destination_receipt']
    source_time=verify_receipt(src,evidence['source_block'],evidence['source_finalized'],evidence['source_tx_hash'])
    dest_time=verify_receipt(dst,evidence['destination_block'],evidence['destination_finalized'],evidence['destination_tx_hash'])
    require(dest_time>=source_time,'Destination timestamp precedes source timestamp.')
    source=source_message(src);match,api_header,api_body=match_api(source,evidence['iris'])
    received=matching_logs(dst,get_cctp_contract('base','MessageTransmitterV2'),{MESSAGE_RECEIVED_V2_TOPIC})
    mints=matching_logs(dst,get_cctp_contract('base','TokenMessengerV2'),{MINT_AND_WITHDRAW_V2_TOPIC,MINT_AND_WITHDRAW_LEGACY_TOPIC})
    require(len(received)==len(mints)==1,'Multi-message or incomplete destination execution remains unresolved.')
    execution=decode_destination_execution(dst,expected_nonce=match.event_nonce)
    require(execution is not None and execution.source_domain==0 and execution.mint_recipient==source.mint_recipient,
        'Destination domain, nonce or recipient mismatch.')
    require(execution.sender_bytes32=='0x'+source.decoded_message.sender_bytes32.hex()
        and execution.finality_threshold_executed==api_header.finality_threshold_executed,
        'Destination sender or executed-finality mismatch.')
    # ABI MessageReceived data has domain,sender,offset,length,messageBody.
    raw=bytes.fromhex(received[0].get('data','0x').removeprefix('0x'))
    require(len(raw)>=128,'Missing received message body.')
    offset=int.from_bytes(raw[64:96],'big')
    require(offset==96 and len(raw)>=offset+32,'Invalid received body offset.')
    length=int.from_bytes(raw[offset:offset+32],'big')
    require(raw[offset+32:offset+32+length]==api_header.message_body,'Received message body differs from Iris evidence.')
    expected=source.amount_base_units-api_body.fee_executed_base_units
    require(execution.mint_and_withdraw_amount==expected,'Destination minted amount does not reconcile with fees.')
    zero='0x'+'0'*64
    transfers=[row for row in matching_logs(dst,get_usdc_contract('base'),{TRANSFER_TOPIC})
        if len(row.get('topics',[]))==3 and row['topics'][1].lower()==zero
        and '0x'+row['topics'][2][-40:].lower()==source.mint_recipient]
    require(len(transfers)==1 and number(transfers[0].get('data'))==expected,'Recipient USDC mint transfer missing, ambiguous or amount-mismatched.')
    return {"schema_version":"checked-cctp-v1","status":"matched_finalized_provider_evidence","data_mode":data_mode,
        "protocol":"Circle CCTP V2","source_network":"ethereum","destination_network":"base",
        "source_tx_hash":source.source_tx_hash,"destination_tx_hash":execution.destination_tx_hash,
        "source_burn_event_reference":source.source_burn_event_reference,"source_message_event_reference":source.source_message_event_reference,
        "destination_receive_event_reference":execution.destination_receive_event_reference,
        "destination_mint_event_reference":execution.destination_mint_event_reference,
        "destination_transfer_event_reference":f'eip155:8453:{execution.destination_tx_hash}:{number(transfers[0]["logIndex"])}',
        "source_block_time":source_time.isoformat(),"destination_block_time":dest_time.isoformat(),
        "source_depositor":source.depositor,"destination_recipient":source.mint_recipient,
        "source_token_contract":get_usdc_contract('ethereum'),"destination_token_contract":get_usdc_contract('base'),
        "source_amount_base_units":str(source.amount_base_units),"fee_base_units":str(api_body.fee_executed_base_units),
        "destination_amount_base_units":str(expected),"decimals":6,"message_nonce":match.event_nonce,
        "attestation_status":"API_REPORTED_COMPLETE","attestation_signature_verified":False,
        "evidence_sha256":trace_digest(evidence),"amount_reconciliation":"matched_exact_base_units",
        "limitations":["Only one-message Ethereum-to-Base USDC CCTP V2 transactions are supported by this strict connector.",
            "Canonicality, receipts and finality rely on configured RPC providers; this application is not a consensus verifier.",
            "Circle attestation signatures were not independently verified by this application.",
            "Successful protocol linkage does not establish real-world ownership, criminality or the victim's allocated funds."]}


async def acquire(settings,payload:CctpRequest, *, partial: dict | None = None):
    """Bounded live acquisition. Secrets/provider URLs never enter stored records."""
    require(settings.ethereum_rpc_url and settings.base_rpc_url,'Ethereum and Base RPC providers must both be configured.')
    records=[];total_bytes=0; evidence={"source_tx_hash":payload.source_tx_hash}
    if partial is not None:partial.update(evidence=evidence,acquisitions=records)
    async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
        async def fetch(key,url,*,rpc_method=None,params=None):
            nonlocal total_bytes
            require(len(records)<96,'Cross-chain provider request budget exhausted.')
            body={'jsonrpc':'2.0','id':len(records)+1,'method':rpc_method,'params':params} if rpc_method else None
            async with client.stream('POST' if rpc_method else 'GET',url,json=body,
                    params=None if rpc_method else {'transactionHash':payload.source_tx_hash}) as response:
                response.raise_for_status();chunks=[];size=0
                async for chunk in response.aiter_bytes():
                    size+=len(chunk);total_bytes+=len(chunk)
                    require(size<=2_000_000 and total_bytes<=16_000_000,'Cross-chain response byte budget exhausted.')
                    chunks.append(chunk)
                import json
                value=json.loads(b''.join(chunks))
            if rpc_method:
                require(isinstance(value,dict) and value.get('id')==body['id'] and 'error' not in value and 'result' in value,
                        'RPC provider returned an error or invalid response.')
                result=value['result']
            else:result=value
            records.append({'provider':key,'method':rpc_method or 'GET Iris v2/messages/0','params':params,
                'retrieved_at':dt.datetime.now(dt.UTC).isoformat(),'response':value,'response_sha256':trace_digest(value)})
            return result
        async def rpc(network,method,params):
            return await fetch(network+'_rpc',getattr(settings,network+'_rpc_url'),rpc_method=method,params=params)
        evidence['ethereum_chain_id']=await rpc('ethereum','eth_chainId',[])
        evidence['base_chain_id']=await rpc('base','eth_chainId',[])
        require(number(evidence['ethereum_chain_id'])==1 and number(evidence['base_chain_id'])==8453,'Configured RPC endpoints are on the wrong networks.')
        evidence['source_receipt']=await rpc('ethereum','eth_getTransactionReceipt',[payload.source_tx_hash])
        require(isinstance(evidence['source_receipt'],dict),'Source transaction receipt unavailable.')
        evidence['source_block']=await rpc('ethereum','eth_getBlockByNumber',[evidence['source_receipt']['blockNumber'],False])
        evidence['source_finalized']=await rpc('ethereum','eth_getBlockByNumber',['finalized',False])
        source_time=verify_receipt(evidence['source_receipt'],evidence['source_block'],evidence['source_finalized'],payload.source_tx_hash)
        require(source_time<=dt.datetime.now(dt.UTC)+dt.timedelta(seconds=60),'Provider source timestamp is in the future.')
        source=source_message(evidence['source_receipt'])
        evidence['iris']=await fetch('circle_iris','https://iris-api.circle.com/v2/messages/0')
        match,_,_=match_api(source,evidence['iris'])
        evidence['destination_finalized']=await rpc('base','eth_getBlockByNumber',['finalized',False])
        require(isinstance(evidence['destination_finalized'],dict),'Destination finalized header unavailable.')
        final_height=number(evidence['destination_finalized'].get('number'))
        dest_tx=payload.destination_tx_hash
        scope={'destination_lookup':'explicit_transaction' if dest_tx else 'bounded_nonce_log_search'}
        if not dest_tx:
            if payload.destination_from_block is not None:
                low=payload.destination_from_block;high=min(payload.destination_to_block,final_height)
            else:
                # Binary search Base's provider-finalized chain for the first
                # block timestamp at or after the source event (<= 64 calls).
                left,right=0,final_height;target=int(source_time.timestamp())
                while left<right:
                    mid=(left+right)//2;b=await rpc('base','eth_getBlockByNumber',[hex(mid),False])
                    require(isinstance(b,dict) and number(b.get('number'))==mid,'Historical Base block unavailable or mismatched.')
                    if number(b.get('timestamp'))<target:left=mid+1
                    else:right=mid
                low=max(0,left-1);high=min(final_height,low+49999)
            require(low<=high,'Destination block range has no finalized blocks.')
            scope.update(from_block=low,to_block=high,all_time_search=False)
            txs=set()
            for start in range(low,high+1,2000):
                rows=await rpc('base','eth_getLogs',[{'address':get_cctp_contract('base','MessageTransmitterV2'),
                    'fromBlock':hex(start),'toBlock':hex(min(start+1999,high)),
                    'topics':[MESSAGE_RECEIVED_V2_TOPIC,None,match.event_nonce]}])
                require(isinstance(rows,list),'Provider log response is not a list.')
                for row in rows:
                    if row.get('removed') is False and row.get('address','').lower()==get_cctp_contract('base','MessageTransmitterV2') and len(row.get('topics',[]))>=3 and row['topics'][2].lower()==match.event_nonce.lower():
                        require(low<=number(row.get('blockNumber'))<=high,'Provider log is outside requested range.')
                        txs.add(row.get('transactionHash'))
            require(len(txs)==1 and re.fullmatch(HASH_PATTERN,next(iter(txs)) or '') is not None,
                    'Destination not uniquely found in bounded finalized scope; unresolved, not proof of no transfer.')
            dest_tx=next(iter(txs)).lower()
        evidence['destination_tx_hash']=dest_tx
        evidence['destination_receipt']=await rpc('base','eth_getTransactionReceipt',[dest_tx])
        require(isinstance(evidence['destination_receipt'],dict),'Destination receipt unavailable.')
        evidence['destination_block']=await rpc('base','eth_getBlockByNumber',[evidence['destination_receipt']['blockNumber'],False])
        result=verify_components(evidence,data_mode='LIVE')
        result['acquisition_scope']=scope;result['provider_requests']=len(records)
        return {'result':result,'evidence':evidence,'acquisitions':records}
