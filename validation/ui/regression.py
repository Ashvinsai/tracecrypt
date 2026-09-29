"""Read-only browser regressions. Start the local synthetic server first.
Usage: python validation/ui/regression.py [http://127.0.0.1:8010]
Requires Playwright and Chromium; does not contact a blockchain provider.
"""
import json
import os
import sys
from browser_harness import open_workspace
from playwright.sync_api import sync_playwright

url = (sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8010') + '/workspace/'
results = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440, 'height':1080})
    client = open_workspace(page, url.removesuffix("/workspace/"))
    page.wait_for_function('typeof state !== "undefined" && state.result && state.graph')
    ambiguous = page.evaluate('''() => state.result.graph.edges.filter(e => e.ordering_ambiguous).every(e => {
      const i = state.result.graph.edges.indexOf(e);
      return Boolean(state.graph.body.data.edges.get(i).dashes);
    })''')
    results.append({'test':'ordering-ambiguous transfers stay visually qualified', 'pass':ambiguous})
    page.evaluate("async () => { const r=await api('/workspace/demo/recorded-okx-direct'); renderResult(r); }")
    mode = page.evaluate("document.getElementById('mode').textContent === state.config.data_mode")
    results.append({'test':'opening recorded evidence does not change the deployment mode badge', 'pass':mode})
    page.set_viewport_size({'width':390, 'height':844})
    page.wait_for_timeout(100)
    overflow = page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    results.append({'test':'mobile overview has no document-level horizontal overflow', 'pass':overflow})
    client.close(); browser.close()
print(json.dumps(results, indent=2))
sys.exit(0 if all(r['pass'] for r in results) else 1)
