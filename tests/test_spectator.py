"""Regression checks for indirect role leaks in ordinary spectator mode."""
import copy
import unittest
from mafia import engine as e


class SpectatorTests(unittest.TestCase):
    def test_night_activity_and_mood_do_not_identify_special_roles(self):
        g = e.new_game()
        e.phase(g, 'night', [p['id'] for p in g['players'] if p['role'] != 'human'])
        task = e.next_task(g)
        before = copy.deepcopy(g)
        self.assertIsNone(e.spectator(g)['active'])
        self.assertEqual(e.spectator(g, True)['active'], task['actor'])
        self.assertEqual(g, before)
        e.apply(g, task, {'target': None, 'mood': 'nervous', 'memo': 'SECRET'})
        self.assertTrue(all('mood' not in p for p in e.spectator(g)['players']))
        self.assertTrue(all('role' not in p and 'notes' not in p for p in e.spectator(g)['players']))
        self.assertEqual(next(p for p in e.spectator(g, True)['players'] if p['id'] == task['actor'])['mood'], 'nervous')

    def test_night_error_notice_does_not_name_actor(self):
        g = e.new_game()
        e.phase(g, 'night', [p['id'] for p in g['players'] if p['role'] != 'human'])
        e.apply(g, e.next_task(g), {'warning': 'Connection interrupted', 'fallback': True})
        notices = [event for event in e.spectator(g)['events'] if event['kind'] == 'notice']
        self.assertEqual(len(notices), 1)
        self.assertIsNone(notices[0]['actor'])


if __name__ == '__main__':
    unittest.main()
