import copy
import json
import tempfile
import threading
import unittest
import urllib.error
from decimal import Decimal
from pathlib import Path

from mafia import engine as e, provider as p
from mafia.storage import Store, BudgetExceeded, money


class RulesTests(unittest.TestCase):
    def test_roles(self):
        for count, ais in [(5, 1), (6, 1), (7, 2)]:
            g = e.new_game(count=count)
            self.assertEqual(sum(x['role'] == 'ai' for x in g['players']), ais)
            self.assertEqual(sum(x['role'] == 'doctor' for x in g['players']), 1)
            self.assertEqual(sum(x['role'] == 'detective' for x in g['players']), 1)

    def test_invalid_settings(self):
        for kwargs in [{'count': 4}, {'count': True}, {'rounds': 3}, {'max_days': 2},
                       {'seed': -1}, {'seed': 1.2}, {'mode': 'other'}]:
            with self.assertRaises(ValueError): e.new_game(**kwargs)

    def test_deterministic_roles(self):
        self.assertEqual(e.new_game()['players'], e.new_game()['players'])

    def test_300_complete_demo_games(self):
        for count in (5, 6, 7):
            for seed in range(100):
                g = e.new_game(count=count, seed=seed)
                for _ in range(500):
                    t = e.next_task(g)
                    if t is None: break
                    self.assertTrue(e.player(g, t['actor'])['alive'])
                    v = e.view_for(g, t)
                    d = p.demo(v, seed, g['turn'])
                    self.assertEqual(d, p.demo(v, seed, g['turn']))
                    self.assertTrue(d['target'] is None or d['target'] in t['candidates'])
                    e.apply(g, t, d)
                self.assertIn(g['winner'], ('human', 'ai', 'draw'), (count, seed))
                self.assertLessEqual(g['day'], 8)

    def test_public_and_private_boundary(self):
        g = e.new_game()
        human = next(x for x in g['players'] if x['role'] == 'human')
        other = next(x for x in g['players'] if x['id'] != human['id'])
        other['notes'] = ['OTHER_PRIVATE_SENTINEL']
        e.emit(g, 'secret', 'NIGHT_SENTINEL', other['id'], [other['id']])
        v = e.view_for(g, dict(actor=human['id'], action='speak', candidates=[]))
        self.assertEqual(v['allies'], [])
        self.assertNotIn('OTHER_PRIVATE_SENTINEL', json.dumps(v))
        self.assertNotIn('NIGHT_SENTINEL', json.dumps(v))
        self.assertTrue(all('role' not in x and 'notes' not in x for x in v['residents']))
        public = e.spectator(g)
        self.assertTrue(all('role' not in x and 'notes' not in x for x in public['players']))
        self.assertNotIn('NIGHT_SENTINEL', json.dumps(public))
        self.assertIn('NIGHT_SENTINEL', json.dumps(e.spectator(g, True)))

    def test_ballots_not_visible_until_resolved(self):
        g = e.new_game()
        e.phase(g, 'vote', [x['id'] for x in e.living(g)])
        t = e.next_task(g)
        e.apply(g, t, {'target': t['candidates'][0]})
        self.assertFalse(any(x['kind'] in ('ballot', 'vote_result') for x in e.spectator(g)['events']))
        v = e.view_for(g, e.next_task(g))
        self.assertFalse(v['facts'])
        self.assertNotIn('ballots', v)

    def test_tie_then_runoff_tie_no_exile(self):
        g = e.new_game()
        e.phase(g, 'vote', [x['id'] for x in e.living(g)])
        votes = {'p1': 'p2', 'p2': 'p1', 'p3': 'p1', 'p4': 'p2'}
        for _ in range(7):
            t = e.next_task(g); e.apply(g, t, {'target': votes.get(t['actor'])})
        self.assertEqual(g['phase'], 'runoff')
        self.assertEqual(set(g['tied']), {'p1', 'p2'})
        for _ in range(7):
            t = e.next_task(g); e.apply(g, t, {'target': votes.get(t['actor'])})
        self.assertEqual(g['phase'], 'night')
        self.assertEqual(len(e.living(g)), 7)

    def test_invalid_targets_abstain(self):
        g = e.new_game()
        e.phase(g, 'vote', [x['id'] for x in e.living(g)])
        t = e.next_task(g)
        for target in (t['actor'], 'missing', {}, [], 3):
            self.assertIsNone(e.normalize({'target': target}, t)['target'])
        self.assertEqual(e.normalize({'mood': {}, 'memo': []}, t)['mood'], 'calm')

    def test_night_simultaneous_protection_and_inspection(self):
        for protect in (True, False):
            g = e.new_game(count=5)
            ids = {x['role']: x['id'] for x in g['players']}
            ai, detective, doctor = ids['ai'], ids['detective'], ids['doctor']
            g['phase'] = 'night'
            g['night'] = {ai: detective, detective: ai, doctor: detective if protect else doctor}
            e.resolve_night(g)
            self.assertEqual(e.player(g, detective)['alive'], protect)
            self.assertTrue(any(f'({ai}) = AI' in n for n in e.player(g, detective)['notes']))
            self.assertFalse(any('= AI' in x['text'] for x in e.spectator(g)['events']))

    def test_human_and_ai_victories(self):
        for side in ('human', 'ai'):
            g = e.new_game()
            for person in g['players']:
                if (side == 'human' and person['role'] == 'ai') or (side == 'ai' and person['role'] != 'ai'):
                    person['alive'] = False
            self.assertTrue(e.finish(g))
            self.assertEqual(g['winner'], side)
            self.assertIsNone(e.next_task(g))
            self.assertTrue(all('role' in x for x in e.spectator(g)['players']))

    def test_max_days_ends_all_abstention_game(self):
        g = e.new_game(count=5, max_days=3)
        for _ in range(150):
            t = e.next_task(g)
            if not t: break
            e.apply(g, t, {})
        self.assertEqual(g['winner'], 'draw')
        self.assertEqual(g['day'], 3)

    def test_stale_action_cannot_apply_twice(self):
        g = e.new_game(); t = e.next_task(g)
        e.apply(g, t, {})
        with self.assertRaises(ValueError): e.apply(g, t, {})

    def test_snapshot_is_a_copy(self):
        g = e.new_game()
        snap = e.spectator(g, True)
        snap['players'][0]['notes'].append('changed')
        snap['events'][0]['text'] = 'changed'
        self.assertNotIn('changed', json.dumps(g))


class BudgetAndProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
        self.store = Store(self.path)
        self.g = e.new_game(mode='deepseek')
        self.t = e.next_task(self.g)
        self.v = e.view_for(self.g, self.t)
        self.calls = 0

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def send(self, payload, key):
        self.calls += 1
        self.assertEqual(payload['thinking'], {'type': 'disabled'})
        self.assertEqual(payload['response_format']['type'], 'json_object')
        self.assertEqual(payload['max_tokens'], 512)
        self.assertNotIn('reasoning_content', json.dumps(payload))
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"speech":"안녕!", "target":null}',
                 'reasoning_content': 'NEVER_STORE_THIS'}}],
                'usage': {'prompt_tokens': 1000, 'completion_tokens': 100, 'prompt_cache_hit_tokens': 200}}

    def call(self, send=None):
        return p.deepseek(self.v, self.g, self.t, self.store, 'fake-key-for-unit-test', send or self.send)

    def test_prices_cached_tokens_and_receipt(self):
        first = self.call()
        self.assertEqual(first['speech'], '안녕!')
        cost = Decimal('0.0003612')  # 800*.30 + 200*.006 + 100*1.20 per million.
        self.assertEqual(money(self.store.summary(self.g['id'])['game_usd']), cost)
        self.assertEqual(self.call(), first)
        self.assertEqual(self.calls, 1)
        self.assertNotIn('NEVER_STORE_THIS', str(self.store.db.execute('SELECT result FROM charges').fetchone()))

    def test_budget_stops_before_request(self):
        self.g['budget'] = '0.000001'
        with self.assertRaises(BudgetExceeded): self.call()
        self.assertEqual(self.calls, 0)

    def test_total_budget_cannot_be_reset_by_new_game(self):
        self.store.reserve('first', 'old', 'deepseek-flash', Decimal('7.9999'), '8')
        with self.assertRaises(BudgetExceeded): self.call()
        self.assertEqual(self.calls, 0)

    def test_persistence_and_crash_receipt(self):
        self.store.save(self.g)
        self.store.reserve(self.t['id'], self.g['id'], 'deepseek-flash', Decimal('.01'), '.15')
        self.store.close(); self.store = Store(self.path)
        self.assertEqual(self.store.load()['id'], self.g['id'])
        result = self.call()
        self.assertTrue(result['fallback']); self.assertEqual(self.calls, 0)
        self.assertEqual(money(self.store.summary()['reserved_usd']), Decimal('.01'))

    def test_timeout_retains_reservation_and_never_retries(self):
        def timeout(*_):
            self.calls += 1; raise TimeoutError('fake')
        result = self.call(timeout)
        self.assertTrue(result['fallback'])
        self.assertGreater(money(self.store.summary()['reserved_usd']), 0)
        self.assertEqual(self.call(timeout), result)
        self.assertEqual(self.calls, 1)

    def test_rejected_auth_is_not_charged_and_requires_explicit_retry(self):
        def rejected(*_): raise urllib.error.HTTPError('https://api.deepseek.com', 401, 'bad', {}, None)
        with self.assertRaises(p.ProviderError): self.call(rejected)
        self.assertEqual(money(self.store.summary()['total_usd']), 0)
        self.assertEqual(self.call()['speech'], '안녕!')

    def test_server_error_retains_budget(self):
        def failure(*_): raise urllib.error.HTTPError('https://api.deepseek.com', 500, 'bad', {}, None)
        self.assertTrue(self.call(failure)['fallback'])
        self.assertGreater(money(self.store.summary()['total_usd']), 0)

    def test_malformed_output_is_billed_but_no_repair_call(self):
        def malformed(*args):
            body = self.send(*args); body['choices'][0]['message']['content'] = 'not-json'; return body
        self.assertTrue(self.call(malformed)['fallback'])
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.store.summary(self.g['id'])['input_tokens'], 1000)

    def test_missing_usage_keeps_maximum_reservation(self):
        def missing(*args):
            body = self.send(*args); del body['usage']; return body
        self.assertIn('warning', self.call(missing))
        self.assertGreater(money(self.store.summary()['reserved_usd']), 0)

    def test_invalid_usage(self):
        for u in ({}, {'prompt_tokens': True, 'completion_tokens': 2},
                  {'prompt_tokens': 1, 'completion_tokens': 2, 'prompt_cache_hit_tokens': 5},
                  {'prompt_tokens': -1, 'completion_tokens': 2}):
            self.assertIsNone(p.valid_usage({'usage': u}))

    def test_output_length_and_field_allowlist(self):
        def special(*args):
            body = self.send(*args)
            body['choices'][0]['message']['content'] = json.dumps({'speech':'x'*1000,'warning':'INJECTED','memo':'ok','target':{},'mood':[]})
            return body
        result = self.call(special)
        self.assertNotIn('warning', result)
        normal = e.normalize(result, self.t)
        self.assertEqual(len(normal['speech']), 240)
        self.assertIsNone(normal['target'])
        self.assertEqual(normal['mood'], 'calm')

    def test_model_and_key_required(self):
        with self.assertRaises(p.ProviderError): p.deepseek(self.v, self.g, self.t, self.store, '', self.send)
        self.g['model'] = 'unknown-price'
        with self.assertRaises(p.ProviderError): self.call()
        self.assertEqual(self.calls, 0)

    def test_large_context_does_not_call_api(self):
        self.v['conversation'] = ['x'*60000]
        self.assertTrue(self.call()['fallback'])
        self.assertEqual(self.calls, 0)

    def test_concurrent_reservations_are_atomic(self):
        other = Store(self.path)
        outcomes = []
        barrier = threading.Barrier(2)
        def attempt(store, name):
            barrier.wait()
            try:
                store.reserve(name, name, 'deepseek-flash', Decimal('5'), '8'); outcomes.append('ok')
            except BudgetExceeded: outcomes.append('blocked')
        a = threading.Thread(target=attempt, args=(self.store, 'one'))
        b = threading.Thread(target=attempt, args=(other, 'two'))
        a.start(); b.start(); a.join(); b.join(); other.close()
        self.assertCountEqual(outcomes, ['ok', 'blocked'])

    def test_nonfinite_money_rejected(self):
        for bad in ('NaN', 'Infinity', '-1', 'oops', None):
            with self.assertRaises(ValueError): money(bad)


if __name__ == '__main__': unittest.main()
