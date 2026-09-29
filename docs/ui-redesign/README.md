# TraceCrypt / Signal — GUI redesign handoff

## Implemented scope

Redesigned the existing primary FastAPI-served vanilla JavaScript workspace. No second application framework, database, queue or online AI service was introduced. The API, tracing/attribution algorithms, historical evidence and separate React research console were retained.

**Visual system.** Ivory and pale-sage surfaces, dark forest fund-flow canvas, emerald controls, original SVG branding and compact line icons, restrained motion, consistent panels, clear status chips, generous section hierarchy and an optional full dark theme. Fonts come from the local system; no font files or external font requests are bundled.

**Overview.** A wallet quick-start, API-derived evidence counters, an interactive graph of the selected result, a rule-based evidence brief, a filterable saved-evidence library and explicitly qualified connector cards. The library is not a live case feed. The counters describe the selected evidence or available library, not invented organization-wide activity. Unavailable data stays unavailable instead of becoming a false zero.

**Trace workspace.** Progressive-disclosure inputs, a three-step path through scope/evidence/action, a nearest-service strip using the existing attribution summary, custom graph nodes, zoom/fit/focus controls, exact evidence inspector, accessible evidence tabs and existing JSON/report/bundle/request actions. All actual nodes and edges are retained. The overview is a layout of evidence, not a statement of fungible-coin allocation.

**Navigation.** Grouped sidebar, mobile drawer, local command search (Ctrl/Command+K), a short guide, inline sign-in failures, dismissible notices and responsive layouts. Appearance is the only new localStorage value; cases and wallet queries are not persisted there.

**Existing operational tools.** Complaint intake and durable queue, saved cases, monitoring, cross-case leads, cross-chain evidence, decision support and capability views are retained and restyled. No disabled protocol, provider or agency integration has been presented as newly operational.

## Files changed

| File | Responsibility |
| --- | --- |
| `workspace/index.html` | New shell, overview, navigation, graph/inspector framing, dialogs; existing workflow IDs retained. |
| `workspace/style.css` | Light/dark design tokens, components, graph styling, responsive layouts, focus and reduced-motion treatments. |
| `workspace/app.js` | Presentation hooks, default overview, separate deployment/result mode badges, qualified graph edges, stable case/session transitions and export identity. |
| `workspace/operations.js` | Nearest-VASP presentation; existing operations API behavior retained. |
| `workspace/ui.js` | New presentation-only module: overview, command search, themes, guide, responsive controls and concise inspector. |
| `workspace/favicon.svg` | Original vector app mark. |
| `validation/ui/*.py` | Real-API local DOM harness and UI checks. |
| `START_GUI.md`, `README.md` | Startup and navigation guidance. |
| `docs/ui-redesign/`, `validation/ui/results/` | This handoff, test records and actual screenshots. |
| `PACKAGE_MANIFEST.json` | Recomputed hashes/lengths for the delivered source package. |

No backend source, dependency file or React research-console file was changed. Source files intentionally remain compatible with the existing direct static-asset delivery.

## Correctness and privacy improvements

Recorded evidence no longer overwrites the deployment-mode badge. Ordering-ambiguous, unconfirmed, unsuccessful or reconstructed graph events remain dashed/qualified. Exact token amounts never pass through JavaScript Number for display arithmetic.

Selecting another case clears the previous displayed evidence rather than mixing the active case with a stale result. Logout clears private result views, cached case search, input fields and relevant private panels. API requests reject results from an obsolete authentication epoch. Exports capture their saved-run identity before asynchronous work and are cancelled after a session transition. These are UI safeguards, not replacements for server authorization or a comprehensive security audit.

## Evidence and API contracts checked

The implementation uses the supplied routes and response fields, including `/api/v1/workspace/config`, `/workspace/demo`, `/cases`, saved investigations, report/export/request-draft actions, watches and `/operations/` endpoints. It does not invent NCRP/SAHYOG endpoints.

The existing bundled graph library identifies itself as **vis-network 10.1.2**. Relevant official documentation checked during implementation:

- vis-network nodes (SVG image nodes and sizing): https://visjs.github.io/vis-network/docs/network/nodes.html
- vis-network network methods and interaction: https://visjs.github.io/vis-network/docs/network/
- MDN native dialog behavior: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/dialog
- MDN reduced-motion media query: https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion

No library was upgraded or fetched from a CDN. The root runtime requirements remain the original project's.

## Developer notes

`ui.js` consumes the existing `state` and helpers after `app.js` and `operations.js` are loaded. The controller emits `tracecrypt:ready`, `tracecrypt:page`, `tracecrypt:user`, `tracecrypt:case` and `tracecrypt:result` for presentation updates. Network calls still go through the existing backend and organization-scoped contracts.

Design tokens live at the beginning of `style.css` with a `[data-theme="dark"]` override. Do not add new external fonts, fabricated live counters, confidence percentages or an AI label over deterministic results. Keep unknowns, source modes, scope limits and disabled integrations visible when changing presentation.

For workflow verification and environment limitations, read [TEST_RESULTS.md](TEST_RESULTS.md). The screenshots in `screenshots/` are actual Chromium renders of the implemented UI and supplied synthetic evidence, not generated concept images.

## Remaining limitations

Native browser cookie/CORS transport, OS download dialogs, clipboard permission handling, localStorage persistence, Safari/Firefox, Windows/macOS execution and a formal accessibility audit were not verified in this constrained browser environment. Very large graphs still depend on the existing backend scope budgets and the graph library; no national-scale rendering benchmark was performed. Tables may scroll inside their own panels on a narrow screen.

No new live blockchain/provider verification, official agency integration, exchange relationship, fraud-accuracy evaluation, asset freeze, recovery, legal admissibility or production security accreditation is implied. The optional existing ML/research features remain separate from the deterministic overview brief.

## Suggested commit

```text
feat(ui): redesign TraceCrypt investigation workspace with Signal design system
```
