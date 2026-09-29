"""Local-only DOM harness for constrained Chromium environments.

Embeds the actual workspace assets into an about:blank document and relays fetch
through one local httpx session. No API responses are mocked. This exercises
rendering and application workflows, not browser cookie/CORS enforcement.
"""
import base64
from pathlib import Path
import re
import httpx
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]

def open_workspace(page, base_url='http://127.0.0.1:8010'):
    origin = urlsplit(base_url)
    if origin.scheme != 'http' or origin.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('Use a loopback HTTP server; this harness must not contact an external deployment.')
    client = httpx.Client(base_url=base_url, timeout=60)
    def relay(_source, url, options=None):
        options = options or {}
        # Never relay to an external destination.
        if not str(url).startswith('/api/v1/'):
            raise ValueError('UI harness only relays the local application API')
        response=client.request(options.get('method', 'GET'), url,
            headers=options.get('headers', {}), content=options.get('body'))
        return {'body':base64.b64encode(response.content).decode(),
                'status':response.status_code, 'headers':dict(response.headers)}
    page.expose_binding('__localAPI', relay)
    page.add_init_script('window.__UI_LOCAL_HARNESS=true;')
    boot='''<script>window.__UI_LOCAL_HARNESS=true;
      window.__testDownloads=[];window.__testPopups=[];window.__testBlobs=new Map();
      const originalObjectURL=URL.createObjectURL.bind(URL);
      URL.createObjectURL=blob=>{const url=originalObjectURL(blob);window.__testBlobs.set(url,blob);return url;};
      const originalAnchorClick=HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click=function(){if(this.download){window.__testDownloads.push({name:this.download,url:this.href});return;}return originalAnchorClick.call(this);};
      window.open=(url)=>{window.__testPopups.push(String(url));return null;};
      window.fetch=async (url, options={}) => {
        const r=await window.__localAPI(String(url), options);
        const data=Uint8Array.from(atob(r.body),c=>c.charCodeAt(0));
        return new Response(data,{status:r.status,headers:r.headers});
      };
      </script>'''
    html=(ROOT/'workspace/index.html').read_text()
    html=re.sub(r'<link[^>]+href="style.css(?:\?[^\"]*)?"[^>]*>',lambda _:'<style>'+(ROOT/'workspace/style.css').read_text()+'</style>',html)
    def script(match):
        name=match.group(1).split('?')[0]
        content=(ROOT/'workspace'/name).read_text().replace('</script','<\\/script')
        return '<script>'+content+'</script>'
    # Defer is emulated by moving real script content to the end of the body.
    scripts=[]
    for match in re.finditer(r'<script[^>]+src="([^"]+)"[^>]*></script>', html):
        scripts.append(script(match))
    html=re.sub(r'<script[^>]+src="([^"]+)"[^>]*></script>', '',html)
    html=html.replace('</head>',boot+'</head>').replace('</body>',''.join(scripts)+'</body>')
    page.set_content(html, wait_until='load')
    return client
