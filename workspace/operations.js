/* Durable operations UI. Same-origin auth; no external keys or CDN dependencies. */
'use strict';
let operationsLoading=false;
window.renderNearestVasp=function(result){
 const summary=result.intelligence?.attribution_summary,host=$('nearest-vasp');
 if(!summary){host.innerHTML='';return;}
 const rows=summary.nearest_within_observed_scope||[];
 host.innerHTML=`<div class="nearest-strip"><svg class="icon" aria-hidden="true"><use href="#i-bank"/></svg><div><span class="micro-label">NEAREST RECEIVING VASP · OBSERVED SCOPE</span>${rows.length?rows.map(r=>`<h2>${escapeHTML(r.entity_name)}</h2><p>${escapeHTML(r.observed_transfer_hops)} verified transfer hop(s) · ${r.direct_from_reported_wallet?'Directly from the reported wallet':'Via observed intermediaries'} · ${escapeHTML(human(r.address_role))}</p><code>${escapeHTML(r.receiving_address)}</code>`).join(''):'<h2>Not established in this scope</h2><p>No supported receiving VASP was established in the bounded evidence.</p>'}</div><p class="nearest-note">${escapeHTML((summary.limitations||[])[0]||'Attribution is bounded to the saved evidence.')} Sender ownership and victim-fund allocation are not inferred.</p>${details('Attribution evidence, all boundaries and recommendations',summary)}</div>`;
};
window.loadOperations=async function(){
 if(operationsLoading)return; operationsLoading=true;
 try{
  const networks=state.config?.networks.filter(n=>n.supported)||[];
  if(!$('ops-network').options.length)$('ops-network').innerHTML=networks.map(n=>`<option value="${escapeHTML(n.key)}">${escapeHTML(n.name)}</option>`).join('');
  $('ops-demo').disabled=state.config?.data_mode!=='SYNTHETIC';
  if(!state.user){$('ops-overview').innerHTML=empty('Sign in to submit complaints and view your organization’s queue.');$('ops-jobs').innerHTML='';$('ops-signals').innerHTML='';return;}
  const [overview,jobs,signals]=await Promise.all([api('/operations/overview'),api('/operations/jobs'),api('/operations/signals?latest=true')]);
  const c=overview.job_counts;
  const metrics=[['Queued / retry',(c.queued||0)+(c.retry||0),'Persistent jobs'],['Running',c.running||0,'Leased workers'],['Saved runs',(c.succeeded||0)+(c.partial||0),'Completion ≠ attribution'],['Indexed observations',overview.indexed_observations,'Saved-run ledger, not the entire chain']];
  $('ops-overview').innerHTML='<div class="kpis">'+metrics.map(([label,value,note])=>`<div class="kpi"><small>${escapeHTML(label)}</small><b>${value}</b><span>${escapeHTML(note)}</span></div>`).join('')+'</div>';
  $('ops-jobs').innerHTML=jobs.jobs.length?'<div class="table-wrap panel"><table><thead><tr><th>Job / network</th><th>Wallet</th><th>Status</th><th>Attempts</th><th>Action</th></tr></thead><tbody>'+jobs.jobs.map(j=>`<tr><td><code>${escapeHTML(short(j.id))}</code><br>${escapeHTML(j.network_key)}</td><td title="${escapeHTML(j.address)}">${escapeHTML(short(j.address))}</td><td><span class="tag">${escapeHTML(human(j.status))}</span>${j.error_code?'<p>'+escapeHTML(human(j.error_code))+'</p>':''}</td><td>${j.attempts}/${j.max_attempts}</td><td>${j.run_id?`<button class="button small ops-open" data-job="${escapeHTML(j.id)}">Open saved result</button>`:''}${['failed','blocked'].includes(j.status)?`<button class="button small ops-retry" data-id="${escapeHTML(j.id)}">Retry same scope</button>`:''}${['queued','retry','running'].includes(j.status)?`<button class="button small ops-cancel" data-id="${escapeHTML(j.id)}">Cancel</button>`:''}${details('Job details',j)}</td></tr>`).join('')+'</tbody></table></div>'+(jobs.truncated?'<p>Showing 100 most recent jobs.</p>':''):empty('No queued complaints yet. Submit a wallet above.');
  $('ops-jobs').querySelectorAll('.ops-open').forEach(b=>b.onclick=async()=>{try{const j=jobs.jobs.find(j=>j.id===b.dataset.job);state.case=await api('/cases/'+j.case_id);activeCase();renderResult(await api('/cases/'+j.case_id+'/investigations/'+j.run_id));await showPage('investigate');}catch(e){notify(e.message,true);}});
  for(const action of ['retry','cancel'])$('ops-jobs').querySelectorAll('.ops-'+action).forEach(b=>b.onclick=async()=>{try{await post('/operations/jobs/'+b.dataset.id+'/'+action);await window.loadOperations();}catch(e){notify(e.message,true);}});
  $('ops-signals').innerHTML=signals.signals.length?signals.signals.map(s=>`<div class="panel padded"><span class="tag">${escapeHTML(human(s.kind))}</span><p>${escapeHTML(s.created_at)} · ${escapeHTML(s.data_mode)}</p>${details('Signal evidence',s.payload)}${!s.acknowledged_at?`<button class="button small ops-ack" data-id="${s.id}">Acknowledge reviewed</button>`:'<span class="subtle">Acknowledged</span>'}</div>`).join('')+(signals.has_more?'<p>Additional signals available through the cursor API.</p>':''):empty('Signals appear after a queued investigation or a processing failure.');
  $('ops-signals').querySelectorAll('.ops-ack').forEach(b=>b.onclick=async()=>{try{await post('/operations/signals/'+b.dataset.id+'/acknowledge');await window.loadOperations();}catch(e){notify(e.message,true);}});
 }finally{operationsLoading=false;}
};
$('ops-refresh').onclick=()=>window.loadOperations().catch(e=>notify(e.message,true));
$('ops-demo').onclick=()=>{
 if(state.config?.data_mode!=='SYNTHETIC'){notify('Synthetic examples cannot be submitted to this process mode.',true);return;}
 $('ops-ref').value='SYNTHETIC-'+Date.now();$('ops-title').value='Synthetic automated attribution demonstration';$('ops-network').value='tron';
 $('ops-address').value='TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM';$('ops-contract').value='TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY';$('ops-seed').value='tron:tx_seed_multi:0';$('ops-start').value='2026-08-01T00:00';$('ops-cutoff').value='2027-01-01T00:00';
};
$('ops-intake-form').onsubmit=async event=>{event.preventDefault();const button=$('ops-submit');button.disabled=true;try{
 requireUser();const wallet={network_key:$('ops-network').value,address:$('ops-address').value.trim()};
 if($('ops-contract').value.trim())wallet.token_contract=$('ops-contract').value.trim();
 if($('ops-seed').value.trim())wallet.seed_event_reference=$('ops-seed').value.trim();
 const body={external_reference:$('ops-ref').value.trim(),title:$('ops-title').value.trim(),allegation_type:$('ops-type').value,wallets:[wallet]};
 if($('ops-start').value)body.incident_start=$('ops-start').value+':00Z';if($('ops-cutoff').value)body.analysis_cutoff=$('ops-cutoff').value+':00Z';
 const result=await post('/operations/intakes',body);notify(result.duplicate?'Existing intake returned; no duplicate jobs created.':`Accepted ${result.jobs.length} persistent trace job(s).`);await window.loadOperations();
 }catch(e){notify(e.message,true);}finally{button.disabled=false;}};
$('ops-process').onclick=async()=>{const button=$('ops-process');button.disabled=true;try{requireUser();notify('Processing one queued investigation within the configured budgets.');const result=await post('/operations/process-next');notify('Queue result: '+human(result.status));await window.loadOperations();}catch(e){notify(e.message,true);}finally{button.disabled=false;}};
$('ops-ledger').onclick=async()=>{try{requireUser();const ledger=await api('/operations/events');downloadObject(ledger,'indexed-investigation-observations.json');notify('Downloaded up to 100 indexed observations. The cursor in the file retrieves additional pages.');}catch(e){notify(e.message,true);}};
setInterval(()=>{if(state.page==='operations'&&state.user&&!document.hidden)window.loadOperations().catch(e=>notify(e.message,true));},5000);

$('ml-form').addEventListener('submit',async event=>{event.preventDefault();try{
 requireUser();loading('ml-result');const result=await api('/operations/ml-ranking?'+new URLSearchParams({network_key:$('ml-network').value,token_contract:$('ml-token').value}));
 $('ml-result').innerHTML=`<p class="callout">${escapeHTML(human(result.status))} · ${result.eligible_unique_wallets} eligible unique wallets · ${result.scored_count} held-out scores. No fraud probability.</p>`+details('Cohort, scores and limitations',result);
}catch(error){$('ml-result').innerHTML=empty(error.message);notify(error.message,true);}});

async function loadProtocolReviews(){
 requireCase();const data=await api(caseBase()+'/cross-chain');
 $('cctp-reviews').innerHTML=data.reviews.map(row=>`<article class="card"><h3>${escapeHTML(human(row.status))}</h3><p>${escapeHTML(row.created_at)} · ${escapeHTML(row.data_mode)}</p>${details('Verified fields and limitations',row.result)}<div class="actions"><button class="button secondary" data-cc-evidence="${escapeHTML(row.id)}">Download evidence JSON</button>${row.status==='matched_finalized_provider_evidence'?`<button class="button secondary" data-cc-continue="${escapeHTML(row.id)}">${row.continuation_job_id?'View continuation':'Queue recipient trace'}</button>`:''}</div></article>`).join('')||empty('No saved protocol checks for this case.');
 document.querySelectorAll('[data-cc-evidence]').forEach(button=>button.onclick=async()=>{try{const evidence=await api(caseBase()+'/cross-chain/'+button.dataset.ccEvidence+'/evidence');downloadObject(evidence,'cctp-evidence-'+button.dataset.ccEvidence+'.json');}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-cc-continue]').forEach(button=>button.onclick=async()=>{try{const job=await post(caseBase()+'/cross-chain/'+button.dataset.ccContinue+'/continue');notify('Recipient trace job '+job.id+' is '+human(job.status)+'. This does not allocate victim funds.');await showPage('operations');}catch(error){notify(error.message,true);}});
}
$('cctp-refresh').onclick=()=>loadProtocolReviews().catch(error=>notify(error.message,true));
$('cctp-form').addEventListener('submit',async event=>{event.preventDefault();const button=$('cctp-check');try{
 requireCase();if(state.config.data_mode!=='LIVE')throw new Error('Live CCTP verification is disabled in this demonstration mode. Saved examples below remain historical records.');
 const payload={source_tx_hash:$('cctp-source').value.trim()};if($('cctp-destination').value)payload.destination_tx_hash=$('cctp-destination').value.trim();
 for(const [id,key] of [['cctp-start','destination_from_block'],['cctp-end','destination_to_block']])if($(id).value)payload[key]=Number($(id).value);
 button.disabled=true;button.textContent='Checking provider evidence…';const row=await post(caseBase()+'/cross-chain/cctp',payload);notify('Protocol check saved: '+human(row.status));await loadProtocolReviews();
}catch(error){notify(error.message,true);}finally{button.disabled=false;button.textContent='Check and save protocol evidence';}});
