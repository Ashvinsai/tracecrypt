/* TraceCrypt / Signal — presentation and navigation only.
 * The original API owns authorization, evidence, tracing, attribution and export.
 * No new external requests, invented metrics, or wallet-address persistence.
 */
'use strict';
(() => {
  const ui = { filter: 'all', showAll: false, commandIndex: 0, commands: [], caseCache: [], theme: 'light', ready: false };
  const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const clampText = (text, max = 55) => String(text || '').length > max ? String(text).slice(0, max - 1) + '…' : String(text || '');
  const modes = { SYNTHETIC: 'Synthetic', RECORDED_PUBLIC: 'Recorded public', LIVE: 'Live' };
  const getMode = r => r?.display_data_mode || r?.trace?.scope?.data_mode || 'UNKNOWN';
  const usablePresets = () => (state.presets || []).filter(p => p.has_trace);
  const pageItems = [
    ['overview', 'grid', 'Overview', 'Your evidence workspace at a glance'],
    ['investigate', 'graph', 'Trace workspace', 'Trace a reported wallet and inspect fund flows'],
    ['operations', 'inbox', 'Complaint intake', 'Submit complaints and review the durable job queue'],
    ['cases', 'folder', 'Cases & saved runs', 'Open your organization’s saved case evidence'],
    ['monitor', 'pulse', 'Monitoring & alerts', 'Create case-scoped watches and inspect signals'],
    ['correlations', 'link', 'Cross-case leads', 'Compare exact observed addresses across authorized cases'],
    ['crosschain', 'bridge', 'Cross-chain evidence', 'Review supported, protocol-specific transfer evidence'],
    ['decisions', 'spark', 'Decision support', 'Review evidence-linked rules and optional model ranking'],
    ['system', 'sliders', 'Capabilities & access', 'Check deployment scope and integration status']
  ];

  function setTheme(theme) {
    ui.theme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = ui.theme;
    $('theme-toggle').innerHTML = icon(ui.theme === 'dark' ? 'sun' : 'moon');
    $('theme-toggle').setAttribute('aria-label', `Switch to ${ui.theme === 'dark' ? 'light' : 'dark'} theme`);
    $('theme-toggle').title = `Switch to ${ui.theme === 'dark' ? 'light' : 'dark'} theme`;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', ui.theme === 'dark' ? '#111815' : '#f5f6f3');
    try { localStorage.setItem('tracecrypt-appearance', ui.theme); } catch { /* Storage may be disabled. Appearance still works. */ }
  }
  let savedTheme;
  try { savedTheme = localStorage.getItem('tracecrypt-appearance'); } catch { /* No persistence in restricted previews. */ }
  setTheme(savedTheme || 'light');
  $('theme-toggle').onclick = () => setTheme(ui.theme === 'light' ? 'dark' : 'light');

  function toggleSidebar(open) {
    document.body.classList.toggle('sidebar-open', open);
    $('sidebar-scrim').hidden = !open;
    $('menu-toggle').setAttribute('aria-expanded', String(open));
    $('menu-toggle').setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  }
  $('menu-toggle').onclick = () => toggleSidebar(!document.body.classList.contains('sidebar-open'));
  $('sidebar-scrim').onclick = () => toggleSidebar(false);
  document.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', event => {
    event.preventDefault(); showPage(button.dataset.go);
  }));
  window.addEventListener('tracecrypt:page', () => {
    toggleSidebar(false);
    if ($('graph').closest('.graph-panel').classList.contains('graph-expanded')) window.toggleGraphFocus(false);
  });

  function updateProfile() {
    const email = state.user?.email;
    $('profile-name').textContent = email || 'Investigator access';
    $('profile-name').title = email || 'Sign in to your organization';
    $('profile-status').textContent = state.user ? 'Organization-scoped session' : 'Sign in to your workspace';
    $('profile-initials').textContent = email ? email.slice(0, 2).toUpperCase() : 'IV';
  }
  $('profile-open').onclick = () => $('login-open').click();
  window.addEventListener('tracecrypt:user', updateProfile);

  // Clear derived views as well as state, so a different case/session never
  // inherits a hidden copy of the previously selected evidence.
  window.clearSelectedEvidence = () => {
    state.result = null;
    state.graph?.destroy(); state.graph = null;
    $('results').hidden = true; $('welcome').hidden = false;
    for (const id of ['result-title', 'result-subtitle', 'result-warning', 'result-mode', 'kpis', 'nearest-vasp', 'graph', 'graph-warning', 'graph-node-select', 'inspector', 'tab-content']) $(id)?.replaceChildren();
    $('export').disabled = true; $('report').disabled = true;
    $('overview-graph').replaceChildren(); $('overview-brief').replaceChildren();
  };
  window.selectInvestigationCase = async c => {
    window.clearSelectedEvidence();
    state.case = c;
    $('trace-form').reset();
    $('case-reference').value = c.case_reference;
    $('case-title').value = c.title;
    $('address').value = ''; $('seed-event').value = ''; $('cutoff').value = '';
    if (state.config) updateAssets();
    activeCase();
    await showPage('investigate');
    $('trace-intake').open = true;
  };
  window.clearPrivateUI = () => {
    ui.caseCache = []; ui.commands = [];
    state.case = null;
    if (state.result?.id) window.clearSelectedEvidence();
    for (const id of ['cases-content', 'monitor-content', 'correlations-content', 'ops-overview', 'ops-jobs', 'ops-signals', 'ml-result', 'cctp-reviews', 'decisions-content']) $(id)?.replaceChildren();
    for (const id of ['trace-form', 'ops-intake-form', 'watch-form', 'draft-form', 'ml-form', 'cctp-form']) $(id)?.reset();
    if ($('search-dialog').open) $('search-dialog').close();
    if ($('draft-dialog').open) $('draft-dialog').close();
    $('command-results').replaceChildren(); $('command-input').value = '';
    $('quick-address').value = '';
  };

  function populateQuickNetworks() {
    const networks = (state.config?.networks || []).filter(n => n.supported);
    $('quick-network').innerHTML = networks.length ? networks.map(n => `<option value="${escapeHTML(n.key)}">${escapeHTML(n.name)}</option>`).join('') : '<option value="">No supported network</option>';
    if (networks.some(n => n.key === $('network').value)) $('quick-network').value = $('network').value;
  }

  async function newInvestigation(address = '', network = '') {
    state.case = null;
    window.clearSelectedEvidence();
    $('trace-form').reset();
    if (network && [...$('network').options].some(o => o.value === network)) $('network').value = network;
    if (state.config) updateAssets();
    $('address').value = address;
    activeCase();
    await showPage('investigate');
    $('trace-intake').open = true;
    $('address').focus({ preventScroll: true });
    $('notice').hidden = true;
  }
  $('new-investigation').onclick = () => newInvestigation();
  $('quick-trace-form').addEventListener('submit', event => {
    event.preventDefault();
    const address = $('quick-address').value.trim(), network = $('quick-network').value;
    if (!network) { notify('No network is configured for this deployment. Review Capabilities & access.', true); return; }
    if (!address) { $('quick-address').focus(); return; }
    newInvestigation(address, network);
  });

  async function openEvidence(id) {
    if (!id) { notify('No saved demonstration is available in this deployment.', true); return; }
    try {
      const result = await api('/workspace/demo/' + encodeURIComponent(id));
      $('preset').value = id;
      await showPage('investigate');
      renderResult(result);
      $('trace-intake').open = false;
      $('notice').hidden = true;
    } catch (error) { notify(error.message, true); }
  }
  const openSynthetic = () => openEvidence(usablePresets().find(p => p.data_mode === 'SYNTHETIC')?.id || usablePresets()[0]?.id);
  $('explore-demo').onclick = openSynthetic;
  $('welcome-demo').onclick = openSynthetic;
  $('guide-demo').onclick = () => { $('help-dialog').close(); openSynthetic(); };
  for (const id of ['open-focus-graph', 'focus-open']) $(id).onclick = async () => {
    if (!state.result) return openSynthetic();
    await showPage('investigate');
  };
  $('brief-actions').onclick = async () => {
    if (!state.result) return newInvestigation();
    await showPage('investigate');
    state.tab = 'actions'; renderTab();
    $('tab-actions').focus({ preventScroll: true });
    document.querySelector('.evidence-tabs').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
  };

  // Exact string formatting only. Token amounts never pass through Number.
  window.compactGraphAmount = value => {
    let s = String(value ?? '?');
    if (/^-?\d+\.\d+$/.test(s)) s = s.replace(/0+$/, '').replace(/\.$/, '');
    return s.length > 18 ? s.slice(0, 15) + '…' : s;
  };

  const roleStyle = role => ({
    seed: { color: '#d6adaa', fill: '#362c28', icon: 'wallet', name: 'REPORTED WALLET' },
    wallet: { color: '#a3b8aa', fill: '#24392b', icon: 'wallet', name: 'INTERMEDIARY' },
    known_service: { color: '#b6ecc0', fill: '#2c4733', icon: 'bank', name: 'REVIEWED SERVICE' },
    deposit_candidate: { color: '#dbbb81', fill: '#3b3527', icon: 'search', name: 'CANDIDATE ONLY' },
    unresolved: { color: '#dbbb81', fill: '#3b3527', icon: 'help', name: 'UNRESOLVED' },
    mixed: { color: '#d6adaa', fill: '#362c28', icon: 'warning', name: 'MIXED EVIDENCE' }
  }[role] || { color: '#a3b8aa', fill: '#24392b', icon: 'wallet', name: 'OBSERVED WALLET' });
  function symbolMarkup(name) { return document.getElementById('i-' + name)?.innerHTML || ''; }
  window.traceNodeImage = node => {
    const role = roleStyle(node.role);
    const text = node.entity_name ? clampText(node.entity_name, 23) : String(node.address).slice(0, 6) + '…' + String(node.address).slice(-5);
    const name = escapeHTML(text);
    const layer = escapeHTML(String(node.hop_layer || 0).padStart(2, '0'));
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="144" height="66" viewBox="0 0 144 66"><rect x="1" y="1" width="142" height="64" rx="10" fill="${role.fill}" stroke="${role.color}" stroke-opacity=".55"/><rect x="9" y="10" width="23" height="23" rx="6" fill="${role.color}" fill-opacity=".11"/><g transform="translate(13 14) scale(.62)" fill="none" stroke="${role.color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${symbolMarkup(role.icon)}</g><text x="40" y="18" font-family="Arial,sans-serif" font-size="7.2" fill="${role.color}" letter-spacing=".25">${role.name}</text><text x="40" y="30" font-family="Arial,sans-serif" font-size="6.8" fill="#a3b7a8">LAYER ${layer}</text><text x="10" y="51" font-family="Arial,sans-serif" font-size="9.3" fill="#e2ece0">${name}</text></svg>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  };

  function metric(label, value, note, symbol, badge) {
    return `<article class="metric-card"><div class="metric-card-header"><span>${escapeHTML(label)}</span><div class="metric-icon">${icon(symbol)}</div></div><div class="metric-value"><strong>${escapeHTML(value)}</strong><span>${escapeHTML(badge)}</span></div><small>${escapeHTML(note)}</small></article>`;
  }
  function renderOverviewMetrics() {
    const x = state.result?.intelligence;
    const mode = modes[getMode(state.result)] || 'No result selected';
    $('overview-kpis').innerHTML =
      metric('Saved evidence sets', state.demoUnavailable ? '—' : usablePresets().length || (ui.ready ? 0 : '—'), 'Available demonstration library', 'layers', 'Library') +
      metric('Transfer events in focus', x?.graph_metrics?.transfer_count ?? '—', x ? mode + ' · selected evidence' : 'Open an investigation to begin', 'activity', 'Observed') +
      metric('Reviewed service boundaries', x?.service_boundaries?.length ?? '—', 'Within the selected trace only', 'bank', 'Attributed') +
      metric('Behavioral pattern types', x?.risk?.rules_triggered?.length ?? '—', 'Investigative leads, not findings', 'pulse', 'Review');
  }

  function renderOverviewBrief() {
    const result = state.result, x = result?.intelligence;
    if (!x) {
      $('overview-brief').innerHTML = '<div class="brief-eyebrow">YOUR NEXT INVESTIGATION</div><h3 class="brief-title">Start with a single lead.</h3><p class="brief-description">Open saved evidence or trace a reported wallet. The brief will summarize the evidence actually available.</p><div class="brief-row">' + icon('shield') + '<span>Human review stays in control</span></div><p class="brief-caveat">No live case metrics are inferred.</p>';
      $('brief-actions').innerHTML = 'Start an investigation ' + icon('arrow');
      return;
    }
    const boundaries = x.service_boundaries || [];
    const headline = boundaries.length === 1 ? 'A service boundary is in view.' : boundaries.length ? boundaries.length + ' service boundaries in view.' : 'The next boundary is unresolved.';
    const description = boundaries.length ? `${boundaries[0].entity_name}${boundaries.length > 1 ? ' and other reviewed services' : ''}. Review the retained source before taking action.` : 'No supported receiving service is established in this trace. Review the remaining limits and leads.';
    const coverage = x.coverage_status === 'complete_within_scope' ? 'Complete in scope' : human(x.coverage_status);
    $('overview-brief').innerHTML = `<div class="brief-eyebrow">${escapeHTML((modes[getMode(result)] || 'Unknown mode').toUpperCase())} · SELECTED EVIDENCE</div><h3 class="brief-title">${escapeHTML(headline)}</h3><p class="brief-description">${escapeHTML(description)}</p><div class="brief-row">${icon('pulse')}<span>Triage priority</span><span class="tag warning">${escapeHTML(human(x.risk?.priority))}</span></div><div class="brief-row">${icon('shield')}<span>Analysis coverage</span><b>${escapeHTML(coverage)}</b></div><div class="brief-row">${icon('search')}<span>Pattern indicators</span><b>${escapeHTML((x.patterns || []).length)} to review</b></div><p class="brief-caveat">Bounded evidence. Not proof of fraud or ownership.</p>`;
    $('brief-actions').innerHTML = 'Review next actions ' + icon('arrow');
  }

  function renderOverviewGraph() {
    const result = state.result, graph = result?.graph;
    if (!graph?.nodes?.length) {
      $('focus-description').textContent = 'Open a saved investigation to visualize the evidence.';
      $('focus-mode').textContent = 'NO EVIDENCE SELECTED';
      $('overview-graph').innerHTML = '<div class="graph-loading">' + icon('graph') + 'A fund-flow graph will appear here.</div>';
      return;
    }
    $('focus-description').textContent = `${String(result.trace.seed.network_key).toUpperCase()} · ${graph.nodes.length} addresses · ${graph.edges.length} observed transfer events`;
    $('focus-mode').textContent = getMode(result);
    const W = 760, H = 254, nodes = graph.nodes, edges = graph.edges;
    const maxLayer = Math.max(1, ...nodes.map(n => n.hop_layer || 0));
    const layers = new Map();
    for (const node of nodes) { const l = node.hop_layer || 0; if (!layers.has(l)) layers.set(l, []); layers.get(l).push(node); }
    const positions = new Map();
    for (const [layer, list] of layers) {
      list.forEach((n, i) => positions.set(n.address, { x: 44 + (layer / maxLayer) * (W - 96), y: list.length === 1 ? 120 : 38 + i * (H - 97) / Math.max(1, list.length - 1) }));
    }
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="Selected saved evidence graph. Each wallet can be opened in the evidence inspector."><title>Selected saved transaction graph; not a live feed</title><defs><marker id="flow-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M1 1 7 4 1 7" fill="none" stroke="#7a9c83" stroke-width="1.2"/></marker><radialGradient id="service-glow"><stop stop-color="#b2edb9" stop-opacity=".15"/><stop offset="1" stop-color="#b2edb9" stop-opacity="0"/></radialGradient></defs>`;
    for (const e of edges) {
      const from = positions.get(e.from), to = positions.get(e.to);
      if (!from || !to) continue;
      const qualified = e.ordering_ambiguous || e.execution_status !== 'success' || e.confirmation_state !== 'confirmed' || e.derived_from;
      const endNode = nodes.find(n => n.address === e.to);
      const color = qualified ? '#a18a63' : endNode?.role === 'known_service' ? '#c2e6b5' : '#688871';
      const path = e.from === e.to ? `M${from.x - 10},${from.y - 14} C${from.x - 42},${from.y - 62} ${from.x + 42},${from.y - 62} ${from.x + 10},${from.y - 14}` : `M${from.x + 19},${from.y} C${(from.x + to.x) / 2},${from.y} ${(from.x + to.x) / 2},${to.y} ${to.x - 22},${to.y}`;
      svg += `<path d="${path}" fill="none" stroke="${color}" stroke-width="1.2" opacity=".7" ${qualified ? 'stroke-dasharray="4 5"' : ''} marker-end="url(#flow-arrow)"><title>${escapeHTML(e.event_reference)} · ${escapeHTML(e.amount_display)} ${escapeHTML(e.symbol)}${qualified ? ' · qualification required' : ''}</title></path>`;
    }
    // Each rendered node corresponds to an actual node, with no invented links.
    for (const n of nodes) {
      const p = positions.get(n.address), style = roleStyle(n.role);
      const label = ({ seed: 'Reported', wallet: 'Intermediary', known_service: 'Service', deposit_candidate: 'Candidate', unresolved: 'Unresolved' })[n.role] || 'Observed';
      const addr = String(n.address).slice(0, 4) + '…' + String(n.address).slice(-4);
      if (n.role === 'known_service') svg += `<circle cx="${p.x}" cy="${p.y}" r="68" fill="url(#service-glow)"/><circle cx="${p.x}" cy="${p.y}" r="29" fill="none" stroke="#badbae" stroke-opacity=".15"/><circle cx="${p.x}" cy="${p.y}" r="38" fill="none" stroke="#badbae" stroke-opacity=".07"/>`;
      svg += `<g class="flow-node" tabindex="0" role="button" aria-label="Inspect ${escapeHTML(n.entity_name || label)} ${escapeHTML(n.address)}" data-node-address="${escapeHTML(n.address)}"><title>${escapeHTML(n.entity_name || n.role_label)} · ${escapeHTML(n.address)}</title><circle class="node-halo" cx="${p.x}" cy="${p.y}" r="25" fill="none" stroke="${style.color}"/><circle cx="${p.x}" cy="${p.y}" r="19" fill="${style.fill}" stroke="${style.color}" stroke-opacity=".7" stroke-width="1.1"/><g transform="translate(${p.x - 9} ${p.y - 9}) scale(.75)" fill="none" stroke="${style.color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${symbolMarkup(style.icon)}</g><text x="${p.x}" y="${p.y + 35}" text-anchor="middle" fill="${style.color}" font-size="9.2" font-family="Arial,sans-serif">${label}</text><text x="${p.x}" y="${p.y + 49}" text-anchor="middle" fill="#8fa896" font-size="7.6" font-family="Arial,sans-serif">${escapeHTML(addr)}</text></g>`;
    }
    svg += '</svg>';
    $('overview-graph').innerHTML = svg;
    $('overview-graph').querySelectorAll('[data-node-address]').forEach(node => {
      const choose = async () => {
        const n = state.result?.graph?.nodes.find(item => item.address === node.dataset.nodeAddress);
        if (!n) return;
        await showPage('investigate');
        inspect(n); $('graph-node-select').value = n.address;
        setTimeout(() => { state.graph?.selectNodes([n.address]); state.graph?.focus(n.address, { scale: 1, animation: false }); }, 160);
      };
      node.addEventListener('click', choose);
      node.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } });
    });
  }

  function renderLibrary() {
    const all = usablePresets(), filtered = all.filter(p => ui.filter === 'all' || p.data_mode === ui.filter), shown = ui.showAll ? filtered : filtered.slice(0, 4);
    $('library-count').textContent = all.length;
    $('library-visible').textContent = `${shown.length} of ${filtered.length} sets`;
    $('library-all').innerHTML = (ui.showAll ? 'Show less ' : 'View all ') + icon(ui.showAll ? 'chevron-down' : 'arrow');
    $('library-all').setAttribute('aria-expanded', String(ui.showAll));
    if (state.demoUnavailable) { $('library-count').textContent='—';$('library-visible').textContent='Unavailable';$('evidence-library').innerHTML=empty('The saved evidence library is unavailable in this deployment. This is not evidence of an empty history.');return; }
    if (!shown.length) { $('evidence-library').innerHTML = empty('No saved evidence matches this filter. Case records are available separately after sign-in.'); return; }
    $('evidence-library').innerHTML = `<table class="library-table"><thead><tr><th scope="col">Investigation / seed wallet</th><th scope="col">Network</th><th scope="col">Evidence mode</th><th scope="col">Observed outcome</th><th scope="col"><span class="sr-only">Open</span></th></tr></thead><tbody>${shown.map(p => {
      const title = p.title.replace(/^(Synthetic|Recorded):\s*/i, '');
      const network = String(p.network || 'unknown');
      const networkLabel = ({ ethereum: 'ETH', tron: 'TRON', bsc: 'BSC', base: 'BASE' })[network] || network.toUpperCase();
      const symbol = ({ ethereum: '◇', tron: '△', bsc: '◇', base: '−' })[network] || '·';
      return `<tr class="library-row" data-preset="${escapeHTML(p.id)}"><td><button class="library-open" data-preset-open="${escapeHTML(p.id)}" title="${escapeHTML(p.title)}"><b>${escapeHTML(title)}</b><span>${escapeHTML(short(p.address))}</span></button></td><td><span class="chain-label"><span class="chain-logo ${escapeHTML(network)}">${symbol}</span>${escapeHTML(networkLabel)}</span></td><td><span class="tag ${p.data_mode === 'SYNTHETIC' ? 'synthetic' : 'recorded'}">${escapeHTML((modes[p.data_mode] || p.data_mode).toUpperCase())}</span></td><td><span class="boundary-count ${p.known_service ? '' : 'unresolved'}">${icon(p.known_service ? 'check' : 'info')}${p.known_service ? escapeHTML(p.known_service) + ' reviewed' : 'Unresolved'}</span></td><td>${icon('arrow-up').replace('class="icon"', 'class="row-arrow"')}</td></tr>`;
    }).join('')}</tbody></table>`;
    $('evidence-library').querySelectorAll('[data-preset-open]').forEach(button => button.onclick = () => openEvidence(button.dataset.presetOpen));
    $('evidence-library').querySelectorAll('[data-preset]').forEach(row => row.onclick = event => { if (!event.target.closest('button')) openEvidence(row.dataset.preset); });
  }
  $('library-all').onclick = () => { ui.showAll = !ui.showAll; renderLibrary(); };
  document.querySelectorAll('[data-library-filter]').forEach(button => button.onclick = () => {
    ui.filter = button.dataset.libraryFilter; ui.showAll = false;
    document.querySelectorAll('[data-library-filter]').forEach(b => { const active = b === button; b.classList.toggle('selected', active); b.setAttribute('aria-pressed', String(active)); });
    renderLibrary();
  });
  window.renderOverview = () => { renderOverviewMetrics(); renderOverviewBrief(); renderOverviewGraph(); renderLibrary(); };

  // Evidence inspector: concise fields first, the original exact object underneath.
  window.renderEvidenceInspector = obj => {
    if (!obj) return;
    const isNode = Boolean(obj.address), isEdge = Boolean(obj.event_reference);
    const title = isNode ? (obj.entity_name || obj.role_label || human(obj.role)) : isEdge ? 'Observed transfer' : 'Evidence context';
    const reference = obj.address || obj.event_reference || '';
    const pairs = isNode ? [
      ['Graph layer', obj.hop_layer ?? 'Unknown'],
      ['Incoming events', (obj.incoming || []).length],
      ['Outgoing events', (obj.outgoing || []).length],
      ['Attribution', (obj.attribution_statuses || []).map(human).join(', ') || 'Not established']
    ] : isEdge ? [
      ['Amount observed', `${obj.amount_display ?? 'Unknown'} ${obj.symbol || ''}`],
      ['Execution', human(obj.execution_status)], ['Confirmation', human(obj.confirmation_state)],
      ['Event ordering', obj.ordering_ambiguous ? 'Ambiguous' : 'No ambiguity flagged'],
      ['Block time', obj.block_time || 'Unknown'],
      ['Reconstruction', obj.derived_from ? 'Derived; inspect source' : 'Not flagged']
    ] : Object.entries(obj).map(([key, value]) => [human(key), typeof value === 'object' ? JSON.stringify(value) : String(value)]);
    $('inspector').innerHTML = `<div class="inspector-emblem">${icon(isNode ? roleStyle(obj.role).icon : isEdge ? 'activity' : 'shield')}</div><h3 class="inspector-title">${escapeHTML(title)}</h3>${reference ? `<div class="inspector-address"><code>${escapeHTML(reference)}</code></div><button class="text-button inspector-copy" id="copy-evidence-reference">${icon('copy')}Copy ${isNode ? 'address' : 'event reference'}</button>` : ''}<dl class="kv compact-kv">${pairs.map(([key, value]) => `<div><dt>${escapeHTML(key)}</dt><dd>${escapeHTML(value)}</dd></div>`).join('')}</dl>${(obj.notes || []).length ? '<p class="inspector-description">' + escapeHTML(obj.notes.join(' ')) + '</p>' : ''}${isEdge ? `<dl class="kv"><div><dt>From</dt><dd><code>${escapeHTML(obj.from)}</code></dd></div><div><dt>To</dt><dd><code>${escapeHTML(obj.to)}</code></dd></div></dl>` : ''}<p class="inspector-description">${escapeHTML(getMode(state.result))} evidence. No victim-fund allocation or sender ownership is inferred.</p>${details('Complete evidence record', obj)}`;
    if (reference) $('copy-evidence-reference').onclick = async () => {
      try { if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable'); await navigator.clipboard.writeText(reference); notify('Exact evidence reference copied.'); }
      catch { notify('Clipboard access is unavailable. Select and copy the full reference shown in the inspector.', true); }
    };
  };
  function refreshNodeSelect() {
    const nodes = state.result?.graph?.nodes || [];
    $('graph-node-select').innerHTML = nodes.map(n => `<option value="${escapeHTML(n.address)}">${escapeHTML(n.entity_name || n.role_label || human(n.role))} · ${escapeHTML(short(n.address))}</option>`).join('');
    const seed = nodes.find(n => n.role === 'seed') || nodes[0];
    if (seed) { $('graph-node-select').value = seed.address; inspect(seed); }
  }
  $('graph-node-select').onchange = () => {
    const node = state.result?.graph?.nodes.find(n => n.address === $('graph-node-select').value);
    if (!node) return;
    inspect(node); state.graph?.selectNodes([node.address]);
    state.graph?.focus(node.address, { scale: 1, animation: false });
  };
  $('zoom-in').onclick = () => { if (state.graph) state.graph.moveTo({ scale: Math.min(3, state.graph.getScale() * 1.25), animation: false }); };
  $('zoom-out').onclick = () => { if (state.graph) state.graph.moveTo({ scale: Math.max(.08, state.graph.getScale() / 1.25), animation: false }); };
  window.toggleGraphFocus = force => {
    const panel = $('graph').closest('.graph-panel');
    const open = force === undefined ? !panel.classList.contains('graph-expanded') : Boolean(force);
    panel.classList.toggle('graph-expanded', open);
    $('fullscreen').setAttribute('aria-pressed', String(open));
    $('fullscreen').innerHTML = icon(open ? 'close' : 'expand') + (open ? 'Close' : 'Expand');
    document.body.style.overflow = open ? 'hidden' : '';
    setTimeout(() => state.graph?.fit({ animation: false }), 90);
  };
  document.querySelector('.tabs').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('.tab')];
    const index = tabs.indexOf(document.activeElement); if (index < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    state.tab = tabs[next].dataset.tab; renderTab(); tabs[next].focus();
  });
  window.addEventListener('tracecrypt:result', () => { refreshNodeSelect(); window.renderOverview(); });

  // Command palette searches local tools, allow-listed demos and authorized cases.
  function commandItems() {
    return [
      ...pageItems.map(([page, symbol, title, note]) => ({ title, note, symbol, type: 'Tool', search: title + ' ' + note, run: () => showPage(page) })),
      { title: 'New investigation', note: 'Start a new case-scoped trace', symbol: 'plus', type: 'Action', search: 'new investigation trace wallet', run: () => newInvestigation() },
      ...usablePresets().map(p => ({ title: p.title, note: `${String(p.network).toUpperCase()} · ${modes[p.data_mode] || p.data_mode} · ${short(p.address)}`, symbol: 'layers', type: 'Saved evidence', search: p.title + ' ' + p.address + ' ' + p.network + ' ' + p.data_mode, run: () => openEvidence(p.id) })),
      ...(state.user ? ui.caseCache : []).map(c => ({ title: c.case_reference + ' · ' + c.title, note: c.data_mode + ' · authorized case', symbol: 'folder', type: 'Your case', search: c.case_reference + ' ' + c.title, run: () => window.selectInvestigationCase(c) }))
    ];
  }
  function selectCommand(index) {
    ui.commandIndex = Math.max(0, Math.min(index, ui.commands.length - 1));
    $('command-results').querySelectorAll('.command-result').forEach((b, i) => b.classList.toggle('command-active', i === ui.commandIndex));
    $('command-results').querySelectorAll('.command-result')[ui.commandIndex]?.scrollIntoView({ block: 'nearest' });
  }
  function renderCommands() {
    const words = $('command-input').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    ui.commands = commandItems().filter(item => words.every(word => item.search.toLowerCase().includes(word))).slice(0, 30);
    ui.commandIndex = 0;
    $('command-results').innerHTML = ui.commands.length ? ui.commands.map((item, index) => `<button class="command-result ${index ? '' : 'command-active'}" data-command="${index}">${icon(item.symbol)}<div><b>${escapeHTML(item.title)}</b><small>${escapeHTML(item.note)}</small></div><span class="micro-label">${escapeHTML(item.type)}</span></button>`).join('') : empty('No matching tool, authorized case or saved evidence. To trace a new wallet, use the wallet field on the overview.');
    $('command-results').querySelectorAll('[data-command]').forEach(button => button.onclick = () => runCommand(Number(button.dataset.command)));
  }
  function runCommand(index) {
    const item = ui.commands[index]; if (!item) return;
    $('search-dialog').close(); item.run();
  }
  async function openSearch() {
    if (document.querySelector('dialog[open]') && !$('search-dialog').open) return;
    $('command-input').value = '';
    renderCommands();
    if (!$('search-dialog').open) $('search-dialog').showModal();
    $('command-input').focus();
    if (state.user) {
      try {
        const epoch = state.authEpoch, cases = await api('/cases');
        if (state.user && epoch === state.authEpoch) { ui.caseCache = cases; if ($('search-dialog').open) renderCommands(); }
      } catch (error) { notify(error.message, true); }
    }
  }
  $('search-open').onclick = openSearch;
  $('command-close').onclick = () => $('search-dialog').close();
  $('command-input').addEventListener('input', renderCommands);
  $('command-input').addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') { event.preventDefault(); selectCommand(ui.commandIndex + 1); }
    if (event.key === 'ArrowUp') { event.preventDefault(); selectCommand(ui.commandIndex - 1); }
    if (event.key === 'Enter') { event.preventDefault(); runCommand(ui.commandIndex); }
  });
  function openGuide() { if (!document.querySelector('dialog[open]')) $('help-dialog').showModal(); }
  $('help-open').onclick = openGuide;
  $('help-close').onclick = () => $('help-dialog').close();
  document.addEventListener('keydown', event => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(event.target.tagName) || event.target.isContentEditable;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); if ($('search-dialog').open) $('search-dialog').close(); else openSearch(); }
    if (event.key === '?' && !typing && !event.ctrlKey && !event.metaKey) { event.preventDefault(); openGuide(); }
    if (event.key === 'Escape') { toggleSidebar(false); if ($('graph').closest('.graph-panel').classList.contains('graph-expanded')) window.toggleGraphFocus(false); }
  });
  // Native dialogs supply focus containment and Escape handling.
  for (const dialog of document.querySelectorAll('dialog')) dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  });

  window.addEventListener('tracecrypt:ready', () => {
    ui.ready = true;
    populateQuickNetworks(); updateProfile();
    $('connection-label').textContent = state.config ? 'Local API connected' : 'Local API unavailable';
    $('connection-dot').style.background = state.config ? '#74bc8e' : '#c98967';
    const live = state.config?.data_mode === 'LIVE';
    $('cctp-check').disabled = !live;
    $('cctp-check').title = live ? 'Requires an authorized LIVE case and both configured RPC providers' : 'LIVE CCTP verification is disabled in this demonstration mode';
    const demoAvailable = usablePresets().length > 0;
    for (const id of ['explore-demo', 'welcome-demo', 'guide-demo']) $(id).disabled = !demoAvailable;
    renderOverview();
  });
  // A meaningful loading state also remains visible when an API is unavailable.
  renderOverviewMetrics();
})();
