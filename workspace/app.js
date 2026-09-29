/* TraceCrypt Unified. One backend, one evidence contract, local static assets.
 * Amounts remain strings; UI formatting never converts token units to Number.
 */
'use strict';
const $ = id => document.getElementById(id);
const state = {config:null,user:null,case:null,result:null,graph:null,tab:'boundaries',page:'overview',presets:[],authEpoch:0};
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const short = v => !v ? '—' : String(v).length > 24 ? String(v).slice(0,12)+'…'+String(v).slice(-8) : String(v);
const pretty = v => escapeHTML(JSON.stringify(v,null,2));
const human = v => String(v ?? 'unknown').replaceAll('_',' ');
const empty = text => `<div class="empty"><span class="empty-symbol"><svg class="icon" aria-hidden="true"><use href="#i-search"/></svg></span>${escapeHTML(text)}</div>`;
const details = (label,obj) => `<details><summary>${escapeHTML(label)}</summary><pre class="json">${pretty(obj)}</pre></details>`;
let noticeTimer;
function notify(message,isError=false){
 const host=$('notice');host.hidden=false;host.className=isError?'error':'';
 host.setAttribute('role',isError?'alert':'status');
 const text=document.createElement('span');text.textContent=message;
 const close=document.createElement('button');close.className='notice-close';close.type='button';close.textContent='×';close.setAttribute('aria-label','Dismiss notification');close.onclick=()=>host.hidden=true;
 host.replaceChildren(text,close);clearTimeout(noticeTimer);
 if(!isError)noticeTimer=setTimeout(()=>host.hidden=true,6500);
 if(isError&&$('login-dialog').open&&$('login-feedback')){$('login-feedback').textContent=message;$('login-feedback').hidden=false;}
}
async function api(path,options={}){
 const epoch=state.authEpoch;
 const response=await fetch('/api/v1'+path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
 let payload;try{payload=await response.json();}catch{throw new Error(`Unexpected server response (${response.status}).`);}
 if(!response.ok)throw new Error(payload.error?.message||payload.detail||`Request failed (${response.status}).`);
 if(epoch!==state.authEpoch)throw new Error('Session changed while the request was in flight. Reload this view.');
 return payload.data ?? payload;
}
const post=(path,body={})=>api(path,{method:'POST',body:JSON.stringify(body)});
function requireUser(){if(!state.user){$('login-dialog').showModal();throw new Error('Sign in to access organization-scoped case data.');}}
function requireCase(){requireUser();if(!state.case)throw new Error('Select a case in Cases & saved runs, or create one in the trace workspace.');}
function caseBase(){return '/cases/'+encodeURIComponent(state.case.id);}
function savedBase(){return '/cases/'+encodeURIComponent(state.result.case_id)+'/investigations/'+encodeURIComponent(state.result.id);}
function activeCase(){ $('active-case-label').textContent=state.case ? `Case: ${state.case.case_reference}` : state.user ? 'Enter a case reference under Case and incident scope.' : 'Sign in to create and save a case.'; window.dispatchEvent(new Event('tracecrypt:case')); }
function setUser(user){state.authEpoch++;state.user=user;$('login-open').textContent=user?'Sign out':'Sign in';if(!user&&window.clearPrivateUI)window.clearPrivateUI();activeCase();window.dispatchEvent(new Event('tracecrypt:user'));}
function setMode(mode){$('mode').textContent=mode||'UNKNOWN';$('mode').className='pill'+(mode==='SYNTHETIC'?' warning':'');}
function loading(id){$(id).innerHTML='<div class="loading"><span class="spinner"></span>Loading evidence…</div>';}
async function showPage(page){
 if(!$('page-'+page))page='overview';
 const changed=state.page!==page;
 state.page=page;document.querySelectorAll('.page').forEach(n=>n.hidden=n.id!=='page-'+page);
 document.querySelectorAll('.nav[data-page]').forEach(n=>n.classList.toggle('active',n.dataset.page===page));
 $('page-title').textContent=document.querySelector(`.nav[data-page="${page}"] > span`)?.textContent||page;
 document.querySelectorAll('.nav[data-page]').forEach(n=>{if(n.dataset.page===page)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});
 document.title=$('page-title').textContent+' — TraceCrypt';
 try{history.replaceState(null,'','#'+page);}catch{/* Restricted preview documents cannot write history. */}
 if(changed)window.scrollTo({top:0,behavior:'instant'});
 window.dispatchEvent(new CustomEvent('tracecrypt:page',{detail:page}));
 try{
 if(page==='overview'&&window.renderOverview)window.renderOverview();
 if(page==='operations'&&window.loadOperations)await window.loadOperations();
 if(page==='cases')await loadCases();if(page==='monitor')await loadMonitor();if(page==='correlations')await loadCorrelations();
 if(page==='crosschain')await loadCrosschain();if(page==='decisions')await loadDecisions();if(page==='system')await loadSystem();
 if(page==='investigate'&&state.graph)setTimeout(()=>state.graph.fit({animation:false}),60);
 }catch(error){notify(error.message,true);}
}
function populateNetworks(){
 const networks=state.config.networks.filter(n=>n.supported);
 for(const id of ['network','watch-network'])$(id).innerHTML=networks.map(n=>`<option value="${escapeHTML(n.key)}">${escapeHTML(n.name)}</option>`).join('');
 updateAssets();
}
function updateAssets(){
 const network=state.config.networks.find(n=>n.key===$('network').value);
 const assets=network?.assets||[];
 $('asset').innerHTML=assets.length?assets.map(a=>`<option value="${escapeHTML(a.id)}">${escapeHTML(a.symbol)} · ${escapeHTML(short(a.contract))}</option>`).join(''):'<option value="">No configured asset in this mode</option>';
}
function inspect(obj){
 if(window.renderEvidenceInspector){window.renderEvidenceInspector(obj);return;}
 $('inspector').innerHTML='<dl class="kv">'+Object.entries(obj).map(([k,v])=>`<div><dt>${escapeHTML(human(k))}</dt><dd>${escapeHTML(typeof v==='object'?JSON.stringify(v,null,2):String(v??'unknown'))}</dd></div>`).join('')+'</dl>';
}
function renderGraph(){
 if(state.graph){state.graph.destroy();state.graph=null;}
 const graph=state.result.graph;
 if(!graph||!window.vis){$('graph').innerHTML=empty('Graph unavailable. The exact transfer ledger remains available.');return;}
 const qualified=e=>e.execution_status!=='success'||e.confirmation_state!=='confirmed'||Boolean(e.derived_from)||Boolean(e.ordering_ambiguous);
 const colors={seed:'#d6ada8',wallet:'#a3b8aa',known_service:'#b6ecc0',deposit_candidate:'#dbbb81',unresolved:'#dbbb81',mixed:'#d6ada8'};
 const nodes=graph.nodes.map(n=>({id:n.address,
   ...(window.traceNodeImage?{shape:'image',image:window.traceNodeImage(n),shapeProperties:{useImageSize:true},label:''}:{shape:'box',label:short(n.address),font:{color:'#d5e3d7',size:11},color:'#2b4030'}),
   color:{border:colors[n.role]||colors.wallet,background:'#1d3225'},margin:10,level:n.hop_layer||0}));
 const edges=graph.edges.map((e,i)=>({id:i,from:e.from,to:e.to,
   label:graph.edges.length<35?(window.compactGraphAmount?window.compactGraphAmount(e.amount_display):e.amount_display??'?')+' '+(e.symbol||''):'',
   arrows:{to:{enabled:true,scaleFactor:.45}},width:1.25,
   color:{color:qualified(e)?'#8b7654':graph.nodes.find(n=>n.address===e.to)?.role==='known_service'?'#99cda2':'#5c7b64',highlight:'#c9f6cf',hover:'#b8dabf'},
   font:{color:qualified(e)?'#d6bd92':'#aac1b0',size:9,face:'Arial',strokeWidth:4,strokeColor:'#16251e',align:'horizontal'},
   dashes:qualified(e),smooth:{enabled:true,type:'curvedCW',roundness:.09}}));
 state.graph=new vis.Network($('graph'),{nodes,edges},{autoResize:true,physics:false,
   layout:{hierarchical:{enabled:true,direction:'LR',sortMethod:'directed',levelSeparation:177,nodeSpacing:122,treeSpacing:145}},
   interaction:{hover:true,tooltipDelay:160,navigationButtons:false,keyboard:{enabled:true,bindToWindow:false}},edges:{selectionWidth:2}});
 state.graph.on('click',params=>{if(params.nodes.length){const n=graph.nodes.find(v=>v.address===params.nodes[0]);inspect(n);if($('graph-node-select'))$('graph-node-select').value=n.address;}else if(params.edges.length){inspect(graph.edges[params.edges[0]]);}});
 const uncertain=graph.edges.filter(qualified).length;
 $('graph-warning').textContent=`${graph.nodes.length} addresses · ${graph.edges.length} distinct transfer events. ${uncertain?uncertain+' dashed event(s): unverified, ambiguous or reconstructed. See exact qualifiers in the ledger.':'Select a node or transfer to inspect the evidence.'}`;
 setTimeout(()=>state.graph?.fit({animation:false}),70);
}
function renderResult(result){
 state.result=result;$('results').hidden=false;$('welcome').hidden=true;
 const intelligence=result.intelligence,trace=result.trace,mode=result.display_data_mode||trace.scope?.data_mode;
 setMode(state.config?.data_mode);if($('result-mode')){$('result-mode').textContent=mode||'UNKNOWN';$('result-mode').className='tag '+(mode==='SYNTHETIC'?'synthetic':'recorded');}
 $('trace-intake').open=false;
 $('result-title').textContent=result.title||('Saved investigation '+(result.id?short(result.id):''));
 $('result-subtitle').textContent=`${human(trace.seed.network_key)} · ${trace.seed.address} · cutoff ${trace.scope.analysis_cutoff||'unknown'}`;
 $('result-warning').textContent=result.historical_capture?
  `SAVED DEMONSTRATION / ${mode}. Historical evidence is unchanged and has not been reverified by this build. Rule flags are recomputed from verified events only; no live request is being made.`:
  `SAVED CASE SNAPSHOT / ${mode}. ${intelligence.disclaimer}`;
 const cards=[['Verified events',intelligence.graph_metrics.transfer_count,'Only successful, confirmed, positive transfers'],
  ['Reached service boundaries',intelligence.service_boundaries.length,'Reviewed labels; no sender-ownership inference'],
  ['Triage priority',human(intelligence.risk.priority),intelligence.risk.score+' heuristic points · not a probability'],
  ['Coverage',human(intelligence.coverage_status),'Bounded to the declared analysis scope']];
 $('kpis').innerHTML=cards.map(([label,value,note])=>`<div class="kpi"><small>${escapeHTML(label)}</small><b${String(value).length>13?' style="font-size:18px"':''}>${escapeHTML(value)}</b><span>${escapeHTML(note)}</span></div>`).join('');
 $('export').disabled=!result.id;$('report').disabled=!result.id;
 inspect({inspection:'Select a node or transfer',trace_sha256:result.trace_sha256||intelligence.input_trace_sha256,
  saved_case_snapshot:Boolean(result.id),allocation:'Unknown — no victim-fund allocation is asserted'});
 if(window.renderNearestVasp)window.renderNearestVasp(result);
 renderGraph();renderTab();
 window.dispatchEvent(new Event('tracecrypt:result'));
}
function renderTab(){
 if(!state.result)return;
 const x=state.result.intelligence,t=state.result.trace;
 document.querySelectorAll('.tab').forEach(b=>{const active=b.dataset.tab===state.tab;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
 $('tab-content').setAttribute('aria-labelledby','tab-'+state.tab);
 const host=$('tab-content');
 if(state.tab==='boundaries'){
  host.innerHTML=x.service_boundaries.length?`<div class="cards">${x.service_boundaries.map(b=>`<article class="card"><span class="tag">REVIEWED SERVICE</span><h3>${escapeHTML(b.entity_name)}</h3><code>${escapeHTML(b.address)}</code><p>Hop ${escapeHTML(b.hop_depth)} · Role: ${escapeHTML(human(b.address_role))}</p><p>${b.direct_deposit_role_verified?'Deposit role is supported by the retained label.':'Service control is not proof that this is a customer deposit address.'}</p><p>Sender ownership: not inferred. Allocation: ${escapeHTML(human(b.case_amount_basis))}.</p>${details('Attribution source & path',b)}${state.result.id?`<button class="button secondary draft-action" data-address="${escapeHTML(b.address)}">Prepare request draft</button>`:''}</article>`).join('')}</div>`:empty('No supported receiving service boundary was established from the verified events in this result. Unknown does not mean no exchange exists downstream.');
  host.querySelectorAll('.draft-action').forEach(b=>b.onclick=()=>{$('draft-target').value=b.dataset.address;$('draft-dialog').showModal();});
 }else if(state.tab==='patterns'){
  host.innerHTML=`<p class="subtle">${escapeHTML(x.disclaimer)} No flags means unscored, not safe.</p><div class="cards">${x.patterns.map(p=>`<article class="card"><span class="tag">${escapeHTML(human(p.rule))}</span><h3>${escapeHTML(short(p.address)||'Graph-level observation')}</h3><p>${escapeHTML(p.explanation)}</p>${details('Observed values & event references',p)}</article>`).join('')||empty('No configured behavioral rule was triggered by the verified subgraph.')}</div><h3>Observed intermediary wallets</h3><div class="cards">${x.intermediaries.map(i=>`<article class="card"><code>${escapeHTML(i.address)}</code><p>${i.incoming_sources} observed sending addresses · ${i.outgoing_destinations} observed receiving addresses</p><p>Wallet age, emptied balance and common ownership remain unknown.</p>${details('Intermediate-flow evidence',i)}</article>`).join('')||empty('No intermediate receive-and-send address in the verified subgraph.')}</div>`;
 }else if(state.tab==='transfers'){
  const rows=[...(t.seed_transfer?[t.seed_transfer]:[]),...(t.observed_transfers||[])];
  host.innerHTML='<p class="subtle">Exact observed amounts, not allocated victim funds. Unverified or ambiguous events remain distinguishable.</p><div class="table-wrap"><table><thead><tr><th>Event reference</th><th>From</th><th>To</th><th>Amount</th><th>Time</th><th>Execution / finality</th></tr></thead><tbody>'+rows.map(e=>`<tr><td>${escapeHTML(short(e.event_reference))}</td><td class="address" title="${escapeHTML(e.from_address)}">${escapeHTML(short(e.from_address))}</td><td class="address" title="${escapeHTML(e.to_address)}">${escapeHTML(short(e.to_address))}</td><td>${escapeHTML(e.amount_display)} ${escapeHTML(e.asset?.display_symbol)}</td><td>${escapeHTML(e.block_time||'unknown')}</td><td>${escapeHTML(e.execution_status)} / ${escapeHTML(e.confirmation_state)}${e.ordering_ambiguous?'<br><span class="tag warning">Ordering ambiguous</span>':''}${e.derived_from?'<br><span class="tag warning">Reconstructed</span>':''}</td></tr>`).join('')+'</tbody></table></div>'+details('Exact JSON event records',rows);
 }else if(state.tab==='limitations'){
  host.innerHTML=`<div class="callout">${escapeHTML(x.volume_note)}</div>`+(t.limitations||[]).map(l=>`<div class="list-row"><h3>${escapeHTML(human(l.code))}</h3><p>${escapeHTML(l.message)}</p><code>${escapeHTML(l.event_reference||l.address||'')}</code></div>`).join('')+details('Excluded or conflicting events',x.excluded_events)+details('Analysis scope & budgets',{scope:t.scope,budget_use:t.budget_use})+details('Observed gross edge volume (not victim loss)',x.observed_volume)+details('Raw acquisition metadata',t.acquisitions||[]);
 }else{
  host.innerHTML=x.recommendations.map(r=>`<div class="list-row"><h3>${escapeHTML(human(r.action))}</h3><p>${escapeHTML(r.reason)}</p></div>`).join('')+'<p class="callout">No request is sent. NCRP and SAHYOG remain not configured. Do not treat a heuristic score as fraud probability or identification.</p>';
 }
}
async function loadDemo(options={}){const id=$('preset').value;if(!id)return;try{const r=await api('/workspace/demo/'+encodeURIComponent(id));renderResult(r);if(!options.silent)notify('Opened saved evidence; no blockchain provider was called.');}catch(e){notify(e.message,true);}}
async function runTrace(event){
 event.preventDefault();const button=$('trace-submit');
 try{requireUser();const assetId=$('asset').value;if(!assetId)throw new Error('No asset is configured for this network and data mode.');
  if(!state.case){const ref=$('case-reference').value.trim(),title=$('case-title').value.trim();if(!ref||!title){$('trace-intake').open=true;document.querySelector('.intake details').open=true;throw new Error('Enter a case reference and title before saving an investigation.');}
   state.case=await post('/cases',{case_reference:ref,title});activeCase();}
  button.disabled=true;button.textContent='Tracing & preserving evidence…';
  const seed=$('seed-event').value.trim();const body={network_key:$('network').value,address:$('address').value.trim(),asset_id:assetId,
    mode:seed?'incident':'address_discovery',seed_event_reference:seed||null};
  if($('cutoff').value)body.analysis_cutoff=$('cutoff').value+':00Z';
  const result=await post(caseBase()+'/investigations',body);renderResult(result);notify('Investigation saved. Its evidence hash will be checked again when opened or exported.');
 }catch(e){notify(e.message,true);}finally{button.disabled=false;button.textContent='Run & save investigation →';}
}
function downloadObject(value,name){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function loadCases(){
 if(!state.user){$('cases-content').innerHTML=empty('Sign in to access case data. Saved demonstrations remain available without an account.');return;}
 loading('cases-content');const cases=await api('/cases');
 $('cases-content').innerHTML=cases.length?'<div class="panel">'+cases.map(c=>`<div class="case-row"><div><h3>${escapeHTML(c.case_reference)} · ${escapeHTML(c.title)}</h3><p>${escapeHTML(c.data_mode)} · ${escapeHTML(c.created_at)}</p></div><div class="actions"><button class="button secondary case-select" data-id="${escapeHTML(c.id)}">Use case</button><button class="button secondary case-runs-toggle" data-id="${escapeHTML(c.id)}">Saved runs</button></div></div><div class="case-runs" id="runs-${escapeHTML(c.id)}" hidden></div>`).join('')+'</div>':empty('No cases yet. Create your first case in the trace workspace.');
 $('cases-content').querySelectorAll('.case-select').forEach(b=>b.onclick=async()=>{const c=cases.find(c=>c.id===b.dataset.id);await window.selectInvestigationCase(c);notify('Selected '+c.case_reference);});
 $('cases-content').querySelectorAll('.case-runs-toggle').forEach(b=>b.onclick=async()=>{try{const c=cases.find(c=>c.id===b.dataset.id),host=$('runs-'+c.id);host.hidden=false;host.innerHTML='<span class="subtle">Loading saved snapshots…</span>';const data=await api('/cases/'+c.id+'/investigations');host.innerHTML=data.runs.length?data.runs.map(r=>`<button class="button secondary run-open" data-id="${escapeHTML(r.id)}">${escapeHTML(r.created_at)} · ${escapeHTML(human(r.coverage_status))}</button>`).join(''):empty('No saved investigation for this case.');if(data.truncated)host.insertAdjacentHTML('beforeend','<p class="callout">Only the newest 200 runs are listed.</p>');host.querySelectorAll('.run-open').forEach(btn=>btn.onclick=async()=>{try{state.case=c;activeCase();const result=await api('/cases/'+c.id+'/investigations/'+btn.dataset.id);await showPage('investigate');renderResult(result);}catch(e){notify(e.message,true);}});}catch(e){notify(e.message,true);}});
}
async function loadMonitor(){
 if(!state.user||!state.case){$('monitor-content').innerHTML=empty('Sign in and select a case before viewing its watches or alerts.');return;}
 loading('monitor-content');const watches=await api(caseBase()+'/watches');
 $('monitor-content').innerHTML=watches.map(w=>`<div class="panel padded"><h2>${escapeHTML(w.address||w.canonical_address||w.id)}</h2><p class="subtle">${escapeHTML(state.case.case_reference)} · checkpoint ${escapeHTML(w.checkpoint_time||'not polled')} · ${w.is_active?'Active':'Paused'}</p><div class="actions"><button class="button primary poll-watch" data-id="${escapeHTML(w.id)}" ${!w.is_active?'disabled':''}>Poll now</button><button class="button secondary watch-alerts" data-id="${escapeHTML(w.id)}">View alerts</button></div>${details('Watch scope',w)}<div id="alerts-${escapeHTML(w.id)}"></div></div>`).join('')||empty('No watches for this case. Add a network-scoped watch above.');
 $('monitor-content').querySelectorAll('.poll-watch').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const outcome=await post(caseBase()+'/watches/'+b.dataset.id+'/poll');notify(`Poll ${outcome.status}: ${outcome.new_alerts} new alerts; ${outcome.duplicate_events} duplicate observations. Coverage: ${outcome.coverage_status}.`);await loadMonitor();}catch(e){notify(e.message,true);}finally{b.disabled=false;}});
 $('monitor-content').querySelectorAll('.watch-alerts').forEach(b=>b.onclick=async()=>{try{const alerts=await api(caseBase()+'/watches/'+b.dataset.id+'/alerts');$('alerts-'+b.dataset.id).innerHTML=alerts.length?alerts.map(a=>`<div class="list-row"><h3>${escapeHTML(a.event_reference)} · ${escapeHTML(a.state)}</h3><p>${escapeHTML(a.execution_status)} / ${escapeHTML(a.confirmation_state)}</p>${details('Alert evidence',a)}</div>`).join(''):empty('No alerts from this watch.');}catch(e){notify(e.message,true);}});
}
async function loadCorrelations(){
 if(!state.user){$('correlations-content').innerHTML=empty('Sign in to compare cases within your organization.');return;}
 loading('correlations-content');const data=await api('/workspace/correlations');
 $('correlations-content').innerHTML=`<p class="subtle">${data.cases_considered} cases compared. ${data.truncated?'Limited to 500 recent snapshots.':''} Integrity rejections: ${data.integrity_rejections}.</p><div class="cards">`+data.links.map(l=>`<article class="card"><span class="tag">${escapeHTML(l.network_key)} · ${escapeHTML(l.data_mode)}</span><h3>${l.case_count} cases share an observed address</h3><code>${escapeHTML(l.shared_address)}</code><p>${escapeHTML(l.limitation)}</p>${details('Case links and exact event references',l)}</article>`).join('')+'</div>'+(data.links.length?'':empty('No qualifying exact address overlap in the selected saved results.'));
}
async function loadCrosschain(){
 loading('crosschain-content');const data=await api('/demo/cctp');
 $('crosschain-content').innerHTML=`<a class="button secondary" href="/investigator/cross-chain" target="_blank" rel="noopener">Open full cross-chain inspection →</a>`+details('Saved CCTP evidence bundles',data);
}
async function loadDecisions(){
 loading('decisions-content');let data;try{data=await api('/demo/routing');}catch{data={status:'Saved routing artifact list is not available in this mode. Use the full research console.'};}
 $('decisions-content').innerHTML=`<div class="panel padded"><h2>Current investigation: deterministic recommendations</h2>${state.result?state.result.intelligence.recommendations.map(r=>`<div class="list-row"><h3>${escapeHTML(human(r.action))}</h3><p>${escapeHTML(r.reason)}</p></div>`).join(''):empty('Open or run an investigation first.')}</div><a class="button secondary" href="/investigator/decision-support" target="_blank" rel="noopener">Open model evaluation & shadow routing →</a>`+details('Retained routing artifacts',data);
}
async function loadSystem(){
 loading('system-content');const meta=await api('/meta');
 $('system-content').innerHTML=`<div class="callout">NCRP: NOT CONFIGURED · SAHYOG: NOT CONFIGURED · VASP submission: DRAFT ONLY. Provider credentials are never shown here.</div><div class="cards">${(meta.capability_details||[]).map(c=>`<article class="card"><span class="tag">${escapeHTML(human(c.status))}</span><h3>${escapeHTML(c.label)}</h3><p>${escapeHTML(c.detail)}</p></article>`).join('')}</div>`+details('Combined deployment configuration',state.config)+details('Budget configuration',meta.budgets);
}
async function initialize(){
 document.querySelectorAll('.nav[data-page]').forEach(n=>n.onclick=()=>showPage(n.dataset.page));
 document.querySelectorAll('.tab').forEach(n=>n.onclick=()=>{state.tab=n.dataset.tab;renderTab();});
 $('network').onchange=updateAssets;$('load-demo').onclick=loadDemo;$('trace-form').onsubmit=runTrace;
 $('clear-case').onclick=()=>{window.clearSelectedEvidence();state.case=null;activeCase();$('case-reference').value='';$('case-title').value='';notify('Next investigation will require a new case reference and title.');};
 $('login-open').onclick=async()=>{if(state.user){try{await post('/auth/logout');setUser(null);state.case=null;if(state.result?.id){state.result=null;state.graph?.destroy();state.graph=null;$('results').hidden=true;$('welcome').hidden=false;}activeCase();notify('Signed out.');await showPage('overview');}catch(e){notify(e.message,true);}}else $('login-dialog').showModal();};
 $('login-close').onclick=()=>$('login-dialog').close();
 $('login-dialog').addEventListener('close',()=>{if($('login-feedback'))$('login-feedback').hidden=true;});
 $('login-form').onsubmit=async event=>{event.preventDefault();try{await post('/auth/login',{email:$('email').value,password:$('password').value});setUser(await api('/auth/me'));$('password').value='';$('login-dialog').close();notify('Signed in. Case access is scoped to your organization.');await showPage(state.page);}catch(e){notify(e.message,true);}};
 $('fit').onclick=()=>state.graph?.fit({animation:!matchMedia('(prefers-reduced-motion: reduce)').matches});$('fullscreen').onclick=()=>{if(window.toggleGraphFocus)window.toggleGraphFocus();};
 $('download-json').onclick=()=>state.result&&downloadObject(state.result,'tracecrypt-investigation.json');
 $('report').onclick=()=>{if(state.result?.id)window.open('/api/v1'+savedBase()+'/report','_blank','noopener');};
 $('export').onclick=async()=>{if(!state.result?.id)return;const epoch=state.authEpoch,runId=state.result.id,exportPath=savedBase();const button=$('export');button.disabled=true;button.textContent='Building bundle…';try{const response=await fetch('/api/v1'+exportPath+'/export',{credentials:'same-origin'});if(!response.ok){const e=await response.json();throw new Error(e.error?.message||'Export failed');}const blob=await response.blob();if(epoch!==state.authEpoch)throw new Error('Session changed. Export cancelled; sign in and export again.');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='investigation-'+runId+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);notify('Exported the saved evidence, intelligence, CSV tables, PDF and checksum manifest.');}catch(e){notify(e.message,true);}finally{button.disabled=!state.result?.id;button.textContent='Export bundle';}};
 $('refresh-cases').onclick=()=>loadCases().catch(e=>notify(e.message,true));$('refresh-monitor').onclick=()=>loadMonitor().catch(e=>notify(e.message,true));$('refresh-correlations').onclick=()=>loadCorrelations().catch(e=>notify(e.message,true));
 $('watch-form').onsubmit=async e=>{e.preventDefault();try{requireCase();const body={network_key:$('watch-network').value,address:$('watch-address').value.trim(),token_contract:$('watch-token').value.trim()};if($('watch-start').value)body.analysis_start=$('watch-start').value+':00Z';await post(caseBase()+'/watches',body);notify('Watch created. Poll now to read the configured source.');await loadMonitor();}catch(error){notify(error.message,true);}};
 $('draft-close').onclick=()=>$('draft-dialog').close();$('draft-form').onsubmit=async e=>{e.preventDefault();try{requireCase();const data=await post(savedBase()+'/request-draft',{request_kind:$('draft-kind').value,target_address:$('draft-target').value,requesting_agency:$('draft-agency').value,requesting_officer:$('draft-officer').value,alleged_incident_summary:$('draft-summary').value,legal_authority_reference:$('draft-authority').value||null});downloadObject(data,'investigator-request-draft.json');$('draft-dialog').close();notify(`Request ${data.draft.status}. Downloaded for human review; nothing was sent.`);}catch(error){notify(error.message,true);}};
 try{state.config=await api('/workspace/config');populateNetworks();setMode(state.config.data_mode);
  try{setUser(await api('/auth/me'));}catch{setUser(null);}
  try{const presets=await api('/workspace/demo');state.presets=presets;$('preset').innerHTML=presets.filter(p=>p.has_trace).map(p=>`<option value="${escapeHTML(p.id)}">${escapeHTML(p.title)} · ${escapeHTML(p.data_mode)}</option>`).join('');const first=presets.find(p=>p.has_trace&&p.data_mode==='SYNTHETIC');if(first)$('preset').value=first.id;if($('preset').value)await loadDemo({silent:true});}catch(e){state.demoUnavailable=e.message;notify('Saved demo views are unavailable in this deployment. '+e.message);}
 }catch(e){state.demoUnavailable=e.message;setMode('UNAVAILABLE');notify('Startup failed: '+e.message+'. Run python launch.py --prepare to initialize the local database.',true);}
 window.dispatchEvent(new Event('tracecrypt:ready'));
 await showPage(location.hash.slice(1)||'overview');
}
initialize();
