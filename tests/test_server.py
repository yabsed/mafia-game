import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from mafia.server import App, handler_for, load_env
from mafia.storage import Store
from mafia import provider


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Store(Path(self.tmp.name) / 'test.db'))
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(); self.app.close(); self.tmp.cleanup()

    def req(self, path, data=None, headers=None):
        h = {'Content-Type': 'application/json', 'X-Session-Token': self.app.token}
        if headers: h.update(headers)
        req = urllib.request.Request(self.url + path, headers=h,
                                     data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req) as response: return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc: return exc.code, exc.read(), exc.headers

    def test_static_and_config(self):
        code, raw, headers = self.req('/')
        self.assertEqual(code, 200); self.assertIn('나는 AI가 아니야'.encode(), raw)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.app.key = 'SECRET_SENTINEL'
        code, raw, _ = self.req('/api/config')
        self.assertTrue(json.loads(raw)['key_configured'])
        self.assertNotIn(b'SECRET_SENTINEL', raw)

    def test_blocks_bad_origin_host_token(self):
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'X-Session-Token': ''}):
            self.assertEqual(self.req('/api/new', {}, headers)[0], 403)
        self.assertEqual(self.req('/api/state', headers={'Host':'evil.example'})[0], 403)

    def test_no_path_traversal(self):
        self.assertEqual(self.req('/../.env')[0], 404)
        self.assertEqual(self.req('/mafia/provider.py')[0], 404)

    def test_live_requires_key_and_consent(self):
        self.assertEqual(self.req('/api/new', {'mode':'deepseek','consent':True})[0], 400)
        self.app.key = 'fake'
        self.assertEqual(self.req('/api/new', {'mode':'deepseek'})[0], 400)

    def test_invalid_settings_do_not_create_game(self):
        for data in ({'count':100}, {'model':'unknown'}, {'budget':'NaN'}, {'count':True}, {'seed':'str'}):
            self.assertEqual(self.req('/api/new', data)[0], 400)
        self.assertIsNone(self.app.game)

    def test_new_step_save_load_export(self):
        self.assertEqual(self.req('/api/new', {'mode':'demo','count':5})[0], 200)
        gid = self.app.game['id']
        self.assertEqual(self.req('/api/control', {'action':'step'})[0], 200)
        deadline = time.monotonic()+3
        while self.app.game['turn'] < 1 and time.monotonic() < deadline: time.sleep(.01)
        self.assertEqual(self.app.game['turn'], 1)
        self.assertFalse(self.app.playing)
        _, raw, _ = self.req('/api/state'); snap = json.loads(raw)
        self.assertNotIn('role', snap['game']['players'][0])
        self.assertEqual(snap['ledger']['total_usd'], '0')
        _, raw, headers = self.req('/api/export?reveal=1')
        self.assertIn('role', json.loads(raw)['game']['players'][0])
        self.assertIn('.json', headers['Content-Disposition'])
        self.assertEqual(self.req('/api/new', {})[0], 200)
        self.assertEqual(self.req('/api/load', {'id':gid})[0], 200)
        self.assertEqual(self.app.game['turn'], 1)
        self.assertFalse(self.app.playing)

    def test_pause_during_inflight_and_duplicate_step(self):
        original = provider.demo
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set(); release.wait(2); return original(*args)
        with patch('mafia.provider.demo', slow):
            self.req('/api/new', {})
            self.req('/api/control', {'action':'step'})
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.req('/api/control', {'action':'step'})[0], 400)
            self.assertEqual(self.req('/api/new', {})[0], 400)
            self.req('/api/control', {'action':'pause'})
            self.assertFalse(self.app.playing)
            release.set()
            deadline = time.monotonic()+3
            while self.app.busy and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(self.app.game['turn'], 1)
            self.assertFalse(self.app.playing)

    def test_recover_saved_game_is_paused(self):
        self.req('/api/new', {})
        self.app.close()
        self.app = App(Store(Path(self.tmp.name) / 'test.db'))
        self.assertIsNotNone(self.app.game)
        self.assertFalse(self.app.playing)

    def test_api_fault_pauses_without_silent_switch_to_demo(self):
        self.app.key = 'fake'
        self.req('/api/new', {'mode':'deepseek', 'consent':True})
        with patch('mafia.provider.deepseek', side_effect=provider.ProviderError('controlled error')):
            self.req('/api/control', {'action':'step'})
            deadline = time.monotonic()+3
            while not self.app.error and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(self.app.game['mode'], 'deepseek')
        self.assertEqual(self.app.game['turn'], 0)
        self.assertFalse(self.app.playing)
        self.assertEqual(self.app.error, 'controlled error')

    def test_env_file_does_not_execute_commands(self):
        env = Path(self.tmp.name) / '.env'
        env.write_text("DEEPSEEK_API_KEY='$(touch /tmp/NO_EXEC)'\nUNRELATED=hello\n", encoding='utf-8')
        with patch.dict('os.environ', {}, clear=True):
            load_env(env)
            import os
            self.assertEqual(os.environ['DEEPSEEK_API_KEY'], '$(touch /tmp/NO_EXEC)')
            self.assertNotIn('UNRELATED', os.environ)
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY':'existing'}, clear=True):
            load_env(env)
            self.assertEqual(os.environ['DEEPSEEK_API_KEY'], 'existing')


if __name__ == '__main__': unittest.main()
