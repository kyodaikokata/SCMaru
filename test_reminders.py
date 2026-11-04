import unittest
from reminders import Reminders, minutes


class ReminderTests(unittest.TestCase):
    def test_connection_pause_resume_and_acknowledgement(self):
        r = Reminders()
        settings = dict(water=(True, 10), activity=(True, 60))
        self.assertEqual(r.advance(0, False, settings), [])
        self.assertEqual(r.advance(9999, True, settings), [])
        self.assertEqual(r.advance(10599, True, settings), ['water'])
        r.reset('water')
        self.assertEqual(r.elapsed['activity'], 600)
        self.assertEqual(r.advance(10599, False, settings), [])
        self.assertEqual(r.advance(20000, True, settings), [])
        self.assertEqual(r.advance(23000, True, settings), ['water', 'activity'])

    def test_disabling_resets_only_that_timer_and_fractional_minutes(self):
        r = Reminders()
        settings = dict(water=(True, .1), activity=(True, 60))
        r.advance(0, True, settings)
        self.assertEqual(r.advance(6, True, settings), ['water'])
        settings['water'] = (False, .1)
        self.assertEqual(r.advance(7, True, settings), [])
        self.assertEqual(r.elapsed, dict(water=0, activity=7))
        settings['water'] = (True, .1)
        self.assertEqual(r.advance(8, True, settings), [])

    def test_invalid_intervals(self):
        for value in ('', 'abc', 0, -1, 'nan', 'inf', 10081):
            self.assertEqual(minutes(value, 10), 10)
        self.assertEqual(minutes('2.5', 10), 2.5)
