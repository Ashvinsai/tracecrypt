# Start the redesigned TraceCrypt workspace

The Signal GUI is implemented in the supplied application, not a separate mockup. Open `/workspace/` after starting the local Python backend. It needs no Node.js build, external fonts or CDN.

## Windows / PowerShell

Use Python 3.12 or 3.13. From the extracted project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime.txt
.\.venv\Scripts\python.exe launch.py --prepare --with-worker
```

## Linux / macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python launch.py --prepare --with-worker
```

Substitute Python 3.13 when applicable. Open:

```text
http://127.0.0.1:8010/workspace/
```

The launcher creates the local demonstration database and a fresh random session secret. Do not open `workspace/index.html` as a standalone file: its evidence and controls use the application API.

## First look

The overview opens with the existing **SYNTHETIC** multi-hop demonstration. Its wallet addresses, service name, edge amounts and counts come from the supplied fixture. They are not current cybercrime statistics. Use the theme button in the top bar to switch between ivory and dark forest.

Click **Explore a saved demo** to open the trace workspace, or click a wallet node on the overview to inspect that node directly. Expand the graph, select nodes or transfers, and use the tabs for attribution, patterns, exact transfers, limitations and next actions. Large amounts are preserved as strings; shortened graph labels are not financial rounding.

Use **Ctrl/Command + K** to find tools, saved demonstration evidence and, after signing in, authorized cases. Press **?** outside a form field for the guide. **Escape** closes dialogs, mobile navigation and the graph's focus view.

## Create a saved synthetic case

Sign in with the public local demonstration account:

```text
Email:    investigator@example.test
Password: demo-password-change-me
```

Open **Complaint intake**, click **Fill synthetic example**, then **Submit & queue**. The companion worker processes the durable job. Open the saved result from the queue to inspect the evidence, export a bundle or prepare a review-only request draft. The evidence library on the overview is distinct from private **Cases & saved runs**.

Alternatively, the overview wallet field opens a manual trace with the address and selected network. It does not silently submit a trace or create a case. Review the exact asset and case scope first. See the root README for the complete manual fixture and worker instructions.

## Important boundaries

This is an investigative prototype. A UI redesign does not establish exchange ownership, provide new provider access, identify a person or make an official agency connection. NCRP and SAHYOG remain not configured. Request drafts are not submitted. The evidence brief is explicitly rule-based, not a new LLM service. The separate `/investigator` research console and backend algorithms are retained.

Keep the demonstration on localhost. The account above is not suitable for production. Do not put provider credentials or an application database into source control.

## Existing installation

Back up your project before updating. The recommended package is the complete source archive. A workspace-only patch, where provided, replaces `workspace/index.html`, `style.css`, `app.js`, `operations.js`, `ui.js` and `favicon.svg` in the original **TraceCrypt Unified v2** installation; retain its `workspace/vendor` directory and backend. Do not apply it to a different release without checking compatibility.

Hard-refresh the browser after replacing files. Stop with Ctrl+C. For later starts, use `python launch.py --with-worker` in the same virtual environment; preparation is needed only to initialize or validate the local fixture.

For implementation details, verification results and limitations, see [the redesign handoff](docs/ui-redesign/README.md) and [test report](docs/ui-redesign/TEST_RESULTS.md).
