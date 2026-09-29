"""Drive the TraceCrypt workspace and record a ~5 minute captioned demo video.

Scene boundaries follow docs/demo/DEMO_SCRIPT.md so a voice-over can be recorded on top.

Usage (app running on a fresh SYNTHETIC database):
    python launch.py --prepare --with-worker
    uv run --with playwright python scripts/record_demo.py      # writes video/ frames
    cd video && ffmpeg -f concat -safe 0 -i frames.txt \
        -vf "scale=1920:1080,fps=30,tpad=stop_mode=clone:stop_duration=7,format=yuv420p" \
        -c:v libx264 -crf 20 ../tracecrypt-demo.mp4

Set TRACECRYPT_URL to point at another port, and CHROMIUM to a browser binary.
"""
import asyncio
import os
import time
from playwright.async_api import async_playwright

BASE = os.environ.get('TRACECRYPT_URL', 'http://127.0.0.1:8010/workspace/')
W, H = 1600, 900
WALLET = 'TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM'
TOKEN = 'TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY'

OVERLAY_JS = r"""
(() => {
  if (window.__demo) return;
  const css = document.createElement('style');
  css.textContent = `
  #demo-cursor{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;
    transform:translate(-3px,-2px);transition:transform .05s linear}
  #demo-cursor svg{filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
  .demo-ripple{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;z-index:2147483646;
    pointer-events:none;border:3px solid #10b981;animation:demoRipple .6s ease-out forwards}
  @keyframes demoRipple{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}
  #demo-caption{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(20px);opacity:0;
    z-index:2147483645;pointer-events:none;max-width:1100px;background:rgba(15,32,25,.94);color:#fff;
    border-radius:14px;padding:14px 26px 15px;box-shadow:0 10px 30px rgba(0,0,0,.35);
    font:500 19px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;transition:all .35s ease;border:1px solid rgba(16,185,129,.55)}
  #demo-caption.on{opacity:1;transform:translateX(-50%) translateY(0)}
  #demo-caption b{display:block;color:#34d399;font-size:13px;letter-spacing:.14em;text-transform:uppercase;margin-bottom:3px}
  .demo-hl{position:fixed;z-index:2147483644;pointer-events:none;border:3px solid #10b981;border-radius:12px;
    box-shadow:0 0 0 4000px rgba(10,20,15,.28),0 0 22px rgba(16,185,129,.8);transition:all .35s ease}
  #demo-card{position:fixed;inset:0;z-index:2147483646;display:flex;flex-direction:column;align-items:center;
    justify-content:center;background:radial-gradient(circle at 30% 20%,#1f3d30,#0c1813 70%);color:#fff;
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;transition:opacity .6s ease}
  #demo-card .logo{width:92px;height:92px;border-radius:24px;background:#10b981;display:grid;place-items:center;margin-bottom:28px;
    box-shadow:0 0 60px rgba(16,185,129,.45)}
  #demo-card h1{font-size:74px;margin:0;letter-spacing:-.02em;font-weight:750}
  #demo-card h1 span{color:#34d399}
  #demo-card p{font-size:26px;margin:18px 0 0;color:#cfe9dd;max-width:1000px;text-align:center;line-height:1.4}
  #demo-card .tags{display:flex;gap:12px;margin-top:34px;flex-wrap:wrap;justify-content:center}
  #demo-card .tags span{border:1px solid rgba(52,211,153,.6);color:#a7f3d0;border-radius:999px;padding:8px 18px;font-size:17px}
  #demo-card .foot{position:absolute;bottom:34px;font-size:16px;color:#8fb7a5}
  #demo-frame{position:fixed;inset:40px 70px 120px;z-index:2147483640;background:#fff;border-radius:14px;
    box-shadow:0 20px 60px rgba(0,0,0,.5);overflow:hidden;border:2px solid #10b981}
  #demo-frame iframe{width:100%;height:100%;border:0}
  `;
  document.head.appendChild(css);
  const cur = document.createElement('div');
  cur.id = 'demo-cursor';
  cur.innerHTML = '<svg width="22" height="30" viewBox="0 0 22 30"><path d="M2 2 L2 24 L8 18 L12 28 L16 26 L12 17 L20 17 Z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.body.appendChild(cur);
  document.addEventListener('mousemove', e => { cur.style.transform = `translate(${e.clientX-3}px,${e.clientY-2}px)`; }, true);
  document.addEventListener('mousedown', e => {
    const r = document.createElement('div'); r.className = 'demo-ripple';
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    document.body.appendChild(r); setTimeout(() => r.remove(), 700);
  }, true);
  const cap = document.createElement('div'); cap.id = 'demo-caption'; document.body.appendChild(cap);
  window.__demo = {
    caption(title, text) {
      cap.classList.remove('on');
      setTimeout(() => { cap.innerHTML = `<b>${title}</b>${text}`; cap.classList.add('on'); }, 250);
    },
    hideCaption() { cap.classList.remove('on'); },
    highlight(sel, pad = 8) {
      document.querySelectorAll('.demo-hl').forEach(x => x.remove());
      const el = typeof sel === 'string' ? document.querySelector(sel) : sel;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const h = document.createElement('div'); h.className = 'demo-hl';
      Object.assign(h.style, {left: (r.left - pad) + 'px', top: (r.top - pad) + 'px',
        width: (r.width + 2 * pad) + 'px', height: (r.height + 2 * pad) + 'px'});
      document.body.appendChild(h);
    },
    clearHighlight() { document.querySelectorAll('.demo-hl').forEach(x => x.remove()); },
    card(html) {
      let c = document.getElementById('demo-card');
      if (!c) { c = document.createElement('div'); c.id = 'demo-card'; document.body.appendChild(c); }
      c.innerHTML = html; c.style.opacity = '1';
    },
    hideCard() { const c = document.getElementById('demo-card'); if (c) { c.style.opacity = '0'; setTimeout(() => c.remove(), 700); } },
    frame(url) {
      let f = document.getElementById('demo-frame');
      if (!f) { f = document.createElement('div'); f.id = 'demo-frame'; document.body.appendChild(f); }
      f.innerHTML = `<iframe src="${url}"></iframe>`;
    },
    closeFrame() { document.getElementById('demo-frame')?.remove(); },
  };
  window.__lastOpened = null;
  window.open = (url) => { window.__lastOpened = url; return null; };
})();
"""

LOGO = ('<div class="logo"><svg width="54" height="54" viewBox="0 0 24 24" fill="none" stroke="#06281b" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="6" r="2.4"/>'
        '<circle cx="19" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/><path d="M7.2 7.2 10.6 16M16.8 7.2 13.4 16M7.4 6h9.2"/></svg></div>')

INTRO = LOGO + """<h1>Trace<span>Crypt</span></h1>
<p>From a victim-reported wallet to the receiving exchange (VASP),<br>automatically, with evidence an investigator can defend.</p>
<div class="tags"><span>Complaint intake</span><span>Automated tracing</span><span>Nearest VASP</span>
<span>Laundering patterns</span><span>Cross-chain</span><span>Alerts</span><span>Evidence reports</span></div>
<div class="foot">Prototype walkthrough · synthetic demo data · runs locally</div>"""

OUTRO = LOGO + """<h1>Trace<span>Crypt</span></h1>
<p>Reported wallet → traced funds → nearest exchange → evidence package.</p>
<div class="tags"><span>TRON</span><span>Ethereum</span><span>BSC</span><span>Base</span><span>USDC CCTP bridge</span></div>
<div class="foot">github.com/Ashvinsai/tracecrypt</div>"""


class Demo:
    def __init__(self, pg):
        self.pg = pg
        self.t0 = None
        self.mx, self.my = W / 2, H / 2

    def now(self):
        return time.monotonic() - self.t0

    async def until(self, t):
        """Hold the current view until scene time t (seconds)."""
        left = t - self.now()
        if left > 0:
            await self.pg.wait_for_timeout(int(left * 1000))
        else:
            print(f'  ! running {-left:.1f}s behind at t={t}')

    async def js(self, expr, *args):
        await self.pg.evaluate(OVERLAY_JS)
        return await self.pg.evaluate(expr, *args)

    async def cap(self, title, text):
        await self.js('([a,b]) => window.__demo.caption(a,b)', [title, text])

    async def hl(self, sel, pad=8):
        await self.js('([s,p]) => window.__demo.highlight(s,p)', [sel, pad])

    async def unhl(self):
        await self.js('() => window.__demo.clearHighlight()')

    async def move(self, x, y, steps=25):
        await self.pg.mouse.move(x, y, steps=steps)
        self.mx, self.my = x, y

    async def to(self, sel, dx=0.5, dy=0.5):
        loc = self.pg.locator(sel).first
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        await self.move(box['x'] + box['width'] * dx, box['y'] + box['height'] * dy)
        return loc

    async def click(self, sel, pause=350):
        loc = await self.to(sel)
        await self.pg.wait_for_timeout(pause)
        await self.pg.mouse.click(self.mx, self.my)

    async def type(self, sel, text):
        await self.click(sel)
        await self.pg.locator(sel).first.fill('')
        await self.pg.keyboard.type(text, delay=18)

    async def scroll(self, dy, steps=8):
        for _ in range(steps):
            await self.pg.mouse.wheel(0, dy / steps)
            await self.pg.wait_for_timeout(45)

    async def nav(self, page):
        await self.click(f'[data-page="{page}"]')
        await self.pg.wait_for_timeout(900)
        await self.js('() => document.getElementById("main-content")?.scrollTo?.(0,0) || window.scrollTo(0,0)')


async def main():
    os.makedirs('video', exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('CHROMIUM') or None)
        ctx = await browser.new_context(viewport={'width': W, 'height': H}, accept_downloads=True,
                                        device_scale_factor=1)
        pg = await ctx.new_page()
        cdp = await ctx.new_cdp_session(pg)
        frames = []

        async def on_frame(ev):
            ts = ev['metadata']['timestamp']
            path = f'video/f{len(frames):06d}.jpg'
            frames.append((ts, path))
            open(path, 'wb').write(__import__('base64').b64decode(ev['data']))
            try:
                await cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
            except Exception:
                pass
        cdp.on('Page.screencastFrame', lambda ev: asyncio.ensure_future(on_frame(ev)))
        pg.on('pageerror', lambda e: print('PAGE ERROR', e))
        d = Demo(pg)
        wall0 = time.monotonic()
        await pg.goto(BASE)
        await pg.wait_for_timeout(600)
        await d.js('(h) => window.__demo.card(h)', INTRO)
        await pg.wait_for_timeout(300)
        await cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 90, 'maxWidth': W, 'maxHeight': H, 'everyNthFrame': 1})
        d.t0 = time.monotonic()

        # 0:00-0:20 intro card
        await d.until(17)
        await d.js('() => window.__demo.hideCard()')

        # 0:20-0:35 sign in
        await d.cap('Sign in', 'Runs on one laptop. Cases are scoped to the investigator’s unit.')
        await d.click('#login-open')
        await pg.wait_for_timeout(500)
        await d.type('#password', 'demo-password-change-me')
        await d.click('#login-form button[type=submit]')
        await pg.wait_for_timeout(1800)
        await d.until(34)

        # 0:35-1:05 overview
        await d.cap('Overview', 'Evidence library, transfers in focus, reviewed exchange boundaries and behaviour patterns.')
        await d.hl('#overview-kpis')
        await d.move(700, 330)
        await d.until(44)
        await d.cap('Fund-flow preview', 'Reported wallet on the left, the exchange it reached on the right.')
        await d.hl('#overview-graph', 4)
        await d.to('#overview-graph', 0.3, 0.55)
        await d.to('#overview-graph', 0.85, 0.5)
        await d.until(54)
        await d.cap('Evidence brief', 'A plain-language summary: boundary reached, triage priority, coverage and patterns.')
        await d.hl('#overview-brief', 4)
        await d.to('#overview-brief', 0.5, 0.4)
        await d.until(64)
        await d.unhl()

        # 1:05-1:50 complaint intake
        await d.nav('operations')
        await d.cap('Complaint intake', 'Wallets arrive from NCRP / SAHYOG-style complaints through the intake API or this form.')
        await d.until(71)
        await d.click('#ops-demo')
        await pg.wait_for_timeout(500)
        await d.hl('#ops-intake-form', 6)
        await d.cap('Fraud type, network, reported wallet, token',
                    'Investment scam · task-based fraud · sextortion · ransomware · phishing · darknet.')
        await d.to('#ops-type')
        await d.until(79)
        await d.to('#ops-address')
        await d.until(84)
        await d.unhl()
        await d.cap('Submit & queue', 'The complaint becomes a durable job. The background worker picks it up automatically.')
        await d.click('#ops-submit')
        for _ in range(40):
            await pg.wait_for_timeout(700)
            if 'succeeded' in await pg.inner_text('#ops-jobs'):
                break
        await pg.wait_for_timeout(400)
        await d.to('#ops-jobs')
        await d.hl('#ops-jobs', 6)
        await d.cap('Job succeeded', 'Traced and attributed in seconds. The worker also raised a review signal.')
        await d.until(97)
        await d.to('#ops-signals')
        await d.hl('#ops-signals', 6)
        await d.cap('Automated alert', '“Receiving VASP observed” is raised for the investigator to acknowledge.')
        await d.until(106)
        await d.unhl()

        # 1:50-2:50 trace workspace
        await d.cap('Open the saved result', '')
        await d.click('#ops-jobs >> text=Open saved result')
        await pg.wait_for_timeout(1800)
        await d.js('() => window.scrollTo(0,0)')
        await d.to('#nearest-vasp')
        await d.hl('#nearest-vasp', 6)
        await d.cap('Nearest receiving VASP',
                    'Northwind Exchange (fictional demo), 5 verified hops away, deposit address shown. Named only with a reviewed label.')
        await d.until(122)
        await d.to('#kpis')
        await d.hl('#kpis', 6)
        await d.cap('Case summary', '9 verified transfers · 1 service boundary · triage risk: Medium · coverage complete within scope.')
        await d.until(132)
        await d.unhl()
        await d.to('#graph')
        await d.cap('Fund-flow graph', 'Money splits across intermediary wallets. The unresolved branch is reported, not guessed.')
        await d.click('#fullscreen')
        await pg.wait_for_timeout(1200)
        await d.move(W * 0.3, H * 0.6)
        await d.move(W * 0.55, H * 0.55)
        await d.move(W * 0.8, H * 0.62)
        await d.until(146)
        await d.click('#fullscreen')
        await pg.wait_for_timeout(800)
        await d.to('#graph-node-select')
        await d.hl('#inspector', 4)
        await d.cap('Evidence inspector', 'Every wallet with its role, graph layer and incoming / outgoing transfers.')
        opts = await pg.eval_on_selector_all('#graph-node-select option', 'els => els.map(e => e.value)')
        for v in (opts[1], opts[2], opts[-1]):
            await pg.select_option('#graph-node-select', v)
            await pg.wait_for_timeout(2600)
        await d.until(170)
        await d.unhl()

        # 2:50-3:25 tabs
        tabs = [('patterns', 'Laundering patterns', 'Fan-in / fan-out, rapid & repeated forwarding, peeling and cycles: leads, not verdicts.'),
                ('transfers', 'Transfer ledger', 'Exact amounts, timestamps and event IDs for every hop.'),
                ('limitations', 'Scope & limitations', 'What the trace did not cover is stated explicitly.'),
                ('actions', 'Investigative recommendations', 'Preserve evidence, review scope, prepare the VASP request.')]
        ends = [178, 186, 193, 202]
        for (tab, title, text), end in zip(tabs, ends):
            await d.click(f'#tab-{tab}')
            await pg.wait_for_timeout(300)
            await d.js('() => document.getElementById("tab-content").scrollIntoView({block:"center",behavior:"smooth"})')
            await d.cap(title, text)
            await d.until(end)

        # 3:25-3:45 reports
        await d.js('() => window.scrollTo({top:0,behavior:"smooth"})')
        await pg.wait_for_timeout(800)
        await d.hl('#download-json', 4)
        await d.cap('Standard investigation report', 'JSON snapshot, HTML / PDF report and a hash-checked evidence bundle.')
        await d.click('#report')
        await pg.wait_for_timeout(300)
        url = await d.js('() => window.__lastOpened')
        await d.unhl()
        if url:
            await d.js('(u) => window.__demo.frame(u)', url)
            await pg.wait_for_timeout(2500)
            for _ in range(4):
                await d.js('() => document.querySelector("#demo-frame iframe").contentWindow.scrollBy({top:420,behavior:"smooth"})')
                await pg.wait_for_timeout(1500)
        await d.until(218)
        await d.js('() => window.__demo.closeFrame()')
        await d.cap('Export evidence bundle', 'JSON, HTML, PDF and CSV with a SHA-256 checksum manifest.')
        try:
            async with pg.expect_download(timeout=15000) as dl:
                await d.click('#export')
            print('exported', (await dl.value).suggested_filename)
        except Exception as e:
            print('export', e)
        await d.until(225)

        # 3:45-4:10 monitoring
        await d.nav('cases')
        await d.cap('Cases & saved runs', 'Every complaint is a case; select it to monitor its wallets.')
        await pg.wait_for_timeout(700)
        await d.click('#page-cases >> text=Use case >> nth=0')
        await pg.wait_for_timeout(1200)
        await d.nav('monitor')
        await d.cap('Monitoring & alerts', 'Put the reported wallet on a watch. Polling is checkpointed and deduplicated.')
        await d.type('#watch-address', WALLET)
        await d.type('#watch-token', TOKEN)
        await d.click('#watch-start')
        await pg.fill('#watch-start', '2026-08-01T00:00')
        await d.click('#watch-form button[type=submit]')
        await pg.wait_for_timeout(1500)
        await d.click('#page-monitor button:has-text("Poll now")')
        await pg.wait_for_timeout(1800)
        await d.click('#page-monitor button:has-text("View alerts")')
        await pg.wait_for_timeout(1200)
        await d.scroll(350)
        await d.cap('Alerts', 'Each new transfer from a watched wallet raises one alert, never duplicates.')
        await d.until(250)

        # 4:10-4:25 cross-case
        await d.nav('correlations')
        await d.cap('Cross-case leads', 'Compares saved cases for shared wallets: one mule or exchange across many complaints.')
        await d.click('#refresh-correlations')
        await pg.wait_for_timeout(1500)
        await d.until(265)

        # 4:25-4:40 cross-chain
        await d.nav('crosschain')
        await d.cap('Cross-chain evidence', 'USDC bridged Ethereum → Base (Circle CCTP): nonce, domains, recipient and amount are checked.')
        await d.to('#page-crosschain form, #cctp-check')
        await d.hl('#page-crosschain .panel, #page-crosschain form', 6)
        await d.until(280)
        await d.unhl()

        # 4:40-4:52 decision support
        await d.nav('decisions')
        await d.cap('AI/ML risk ranking', 'IsolationForest ranks unusual fund-flow graphs. With under 25 wallets it says so, never a fake score.')
        await d.type('#page-decisions input[type=text], #page-decisions input:not([type])', TOKEN)
        await d.click('#page-decisions button:has-text("Rank eligible saved graphs")')
        await pg.wait_for_timeout(1500)
        await d.scroll(300)
        await d.until(291)

        # 4:52-5:00 capabilities + outro
        await d.nav('system')
        await d.cap('Capabilities & integration status', 'NCRP / SAHYOG intake API ready; live connectors need authorised access.')
        await d.scroll(250)
        await d.until(296)
        await d.js('() => window.__demo.hideCaption()')
        await d.js('(h) => window.__demo.card(h)', OUTRO)
        await d.until(304)
        print(f'total {d.now():.1f}s')
        await cdp.send('Page.stopScreencast')
        await pg.wait_for_timeout(500)
        # concat list with real per-frame durations
        with open('video/frames.txt', 'w') as f:
            for i, (ts, path) in enumerate(frames):
                nxt = frames[i + 1][0] if i + 1 < len(frames) else ts + 0.5
                f.write(f"file '{path.split('/')[-1]}'\nduration {max(nxt - ts, 0.001):.4f}\n")
            f.write(f"file '{frames[-1][1].split('/')[-1]}'\n")
        print('frames', len(frames), 'span', frames[-1][0] - frames[0][0])
        await ctx.close()
        await browser.close()


asyncio.run(main())
