"""Optional UI smoke test. Requires Playwright; no real API or persistent user data.

Default: normal browser navigation. --bridge: renderer + real HTTP bridge for a
sandbox that blocks browser loopback navigation; does not test browser transport.
"""
import argparse
import json
import re
import tempfile
import threading
import urllib.error
import urllib.request
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mafia.server import App, ROOT, handler_for
from mafia.storage import Store


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser()
    parser.add_argument('--bridge', action='store_true')
    parser.add_argument('--chromium', help='Optional installed Chromium executable')
    parser.add_argument('--output', type=Path, default=Path('playwright-report'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        app = App(Store(Path(tmp) / 'test.db'))  # No key; never reads .env.
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                options = {'headless': True}
                if args.chromium: options['executable_path'] = args.chromium
                browser = p.chromium.launch(**options)
                page = browser.new_page(viewport={'width':1440, 'height':1100})
                page.set_default_timeout(10000)
                errors = []
                page.on('pageerror', lambda err: errors.append(str(err)))
                if args.bridge:
                    def bridge(source, path, options=None):
                        options = options or {}
                        if not isinstance(path, str) or not path.startswith('/api/'):
                            raise ValueError('Only this test server API is allowed')
                        req = urllib.request.Request(base + path, headers=options.get('headers', {}),
                            data=options.get('body', '').encode() if options.get('method') == 'POST' else None)
                        try:
                            with urllib.request.urlopen(req, timeout=5) as r:
                                return {'ok': True, 'status': r.status, 'data': json.loads(r.read())}
                        except urllib.error.HTTPError as err:
                            return {'ok': False, 'status': err.code, 'data': json.loads(err.read())}
                    page.expose_binding('localHTTP', bridge)
                    html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
                    html = re.sub(r'<link[^>]+>', '', html)
                    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S)
                    page.set_content(html)
                    page.add_style_tag(content=(ROOT / 'web/style.css').read_text())
                    page.evaluate('''() => {window.fetch = async (path, options) => {
                      const r = await window.localHTTP(path, options);
                      return {ok:r.ok, status:r.status, json:async()=>r.data};
                    };}''')
                    page.add_script_tag(content=(ROOT / 'web/app.js').read_text())
                else:
                    page.goto(base)
                page.wait_for_function("document.querySelector('#connection').textContent.includes('로컬 연결됨')")
                page.click('#new'); page.click('#start')
                page.wait_for_selector('#setup-dialog', state='hidden')
                page.select_option('#speed', '0.3')
                page.wait_for_function("parseInt(document.querySelector('#turn-count').textContent)>=12", timeout=15000)
                page.click('#play'); page.wait_for_timeout(700)
                page.screenshot(path=str(args.output/'desktop.png'), full_page=True)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.click('.resident:nth-child(1)'); page.click('#resident-detail button')
                assert page.locator('.resident.suspect').count() == 1
                page.click('.director label'); page.wait_for_selector('.resident-role')
                page.click('#secret-tab'); page.wait_for_selector('.message.secret')
                page.click('#public-tab'); page.click('.director label')
                page.wait_for_selector('.resident-role', state='hidden')
                with page.expect_download() as download: page.click('#export')
                assert download.value.suggested_filename.endswith('.json')
                page.set_viewport_size({'width':390, 'height':844})
                page.wait_for_timeout(4200)
                page.screenshot(path=str(args.output/'mobile.png'), full_page=True)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                assert not errors, errors
                browser.close()
                print('PASS: desktop/mobile, playback, secrets, suspicion, JSON export; no JS errors.')
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
