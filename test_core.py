import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core import Ledger, batteries, language, normalize, grouped_sc
from connections import Collector


class LedgerTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).parent / '.test-data'
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.ledger = Ledger(self.temp.name)
        self.ledger.attach('123', 'room')
        self.now = int(datetime.now().timestamp())

    def tearDown(self):
        self.ledger.db.close()
        self.temp.cleanup()

    def sc(self, mid='1', text='hello', uid=42, timestamp=None):
        return normalize('room', 'sc', dict(id=mid, uid=uid, uname='Alice', message=text, price=30,
                                           start_time=timestamp or self.now), '123')

    def test_video_and_manual_override(self):
        self.ledger.ingest(self.sc(), video=True)
        self.ledger.ingest(self.sc('2', '看看 https://www.bilibili.com/video/BV1xx411c7mD/'), video=True)
        self.ledger.ingest(self.sc('3', 'BV123 invalid'), video=True)
        self.assertEqual(self.ledger.pending(), 3)
        self.assertEqual([r['mark'] for r in self.ledger.sc_rows()], ['square', '', 'square'])
        self.ledger.mark(self.sc()['id'], 'triangle')
        self.assertEqual(self.ledger.pending(), 3)
        self.assertEqual(self.ledger.sc_rows()[0]['automatic'], 0)

    def test_blue_bulk_confirm_only_current_visible_ledger_and_keeps_revenue(self):
        self.ledger.ingest(self.sc('1'), video=True)
        self.ledger.ingest(self.sc('2'), video=True)
        self.ledger.ingest(self.sc('3'), video=True)
        self.ledger.mark(self.sc('2')['id'], 'triangle')
        self.ledger.delete_sc('123', 'room', ['3'])
        total = self.ledger.rankings('123', 'room', daily=False)[0]['total']
        self.assertEqual(self.ledger.confirm_squares(), 1)
        rows = self.ledger.sc_rows()
        self.assertEqual([r['mark'] for r in rows], ['circle', 'triangle', 'square'])
        self.assertFalse(rows[0]['automatic'])
        self.assertFalse(rows[0]['sunk'])
        self.assertEqual(self.ledger.pending(), 1)
        self.assertEqual(self.ledger.rankings('123', 'room', daily=False)[0]['total'], total)
        self.assertIn('□', self.ledger.export().read_text(encoding='utf-8-sig'))
        self.ledger.archive()
        self.assertEqual(self.ledger.confirm_squares(), 0)

    def test_enable_video_classifies_unmarked_without_overwriting_manual_choices(self):
        for index, text in [('1', 'hello'), ('2', 'BV1xx411c7mD'), ('3', 'manual')]:
            self.ledger.ingest(self.sc(index, text))
        self.ledger.mark(self.sc('3')['id'], 'triangle')
        self.assertEqual(self.ledger.classify_video_sc(), 1)
        self.assertEqual([r['mark'] for r in self.ledger.sc_rows()], ['square', '', 'triangle'])
        self.assertEqual(self.ledger.classify_video_sc(), 0)

    def test_dedup_and_archive_does_not_change_money(self):
        self.assertTrue(self.ledger.ingest(self.sc()))
        self.assertFalse(self.ledger.ingest(self.sc()))
        first = self.ledger.archive()
        self.assertEqual(self.ledger.pending(), 0)
        self.ledger.ingest(self.sc('2'))
        self.ledger.restore(first)
        self.assertEqual(self.ledger.pending(), 2)
        self.assertEqual(self.ledger.rankings('123', 'room')[0]['total'], 60000)
        self.assertEqual(len(self.ledger.export().read_text(encoding='utf-8-sig').split('ID: ')), 3)

    def test_deleted_sc_does_not_mean_refunded(self):
        self.ledger.delete_sc('123', 'room', ['1'])
        self.ledger.ingest(self.sc())
        self.assertEqual(self.ledger.pending(), 0)
        self.assertEqual(self.ledger.rankings('123', 'room')[0]['total'], 30000)

    def test_restart_recovers_marks_and_session(self):
        sid = self.ledger.session
        self.ledger.ingest(self.sc())
        self.ledger.mark(self.sc()['id'], 'triangle')
        self.ledger.db.close()
        self.ledger = Ledger(self.temp.name)
        self.assertEqual(self.ledger.attach('123', 'room'), sid)
        self.assertEqual(self.ledger.sc_rows()[0]['mark'], 'triangle')

    def test_midnight_and_next_broadcast(self):
        start = int(datetime(2026, 11, 4, 23, 0).timestamp())
        first = self.ledger.attach('123', 'room', start)
        self.ledger.ingest(self.sc('night', timestamp=start + 60))
        self.ledger.ingest(self.sc('after-midnight', timestamp=start + 7200))
        self.assertEqual(self.ledger.attach('123', 'room', start), first)
        self.assertEqual(self.ledger.pending(), 2)
        self.assertEqual(self.ledger.rankings('123', 'room', daily=False)[0]['total'], 60000)
        new_start = start + 20 * 3600
        second = self.ledger.attach('123', 'room', new_start)
        self.assertNotEqual(first, second)
        self.assertEqual(self.ledger.pending(), 0)
        self.assertEqual(self.ledger.rankings('123', 'room', daily=False), [])
        self.assertFalse(self.ledger.ingest(self.sc('stale-replay', timestamp=start + 60)))
        self.ledger.ingest(self.sc('new', timestamp=new_start + 1))
        self.assertEqual(self.ledger.pending(), 1)
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM events WHERE session=?', (first,)).fetchone()[0], 2)

    def test_end_without_clearing_still_creates_new_session(self):
        first = self.ledger.session
        self.ledger.ingest(self.sc())
        self.ledger.end()
        self.assertEqual(self.ledger.pending(), 1)
        self.assertNotEqual(self.ledger.attach('123', 'room'), first)
        self.assertEqual(self.ledger.pending(), 0)

    def test_daily_separate_from_session_and_scope(self):
        yesterday = datetime.now().replace(hour=12) - timedelta(days=1)
        self.ledger.ingest(self.sc(timestamp=int(yesterday.timestamp())))
        self.ledger.ingest(self.sc('2'))
        self.assertEqual(self.ledger.rankings('123', 'room')[0]['total'], 30000)
        self.assertEqual(self.ledger.rankings('123', 'room', daily=False)[0]['total'], 60000)
        self.assertEqual(self.ledger.rankings('456', 'room'), [])
        self.assertEqual(self.ledger.rankings('123', 'blivechat'), [])

    def test_unknown_users_are_not_combined(self):
        self.ledger.ingest(self.sc('1', uid=0))
        self.ledger.ingest(self.sc('2', uid=0))
        self.assertEqual(len(self.ledger.rankings('123', 'room')), 2)

    def test_free_discount_blind_and_guard(self):
        gift = dict(tid='g1', uid=42, uname='Alice', gift_name='gift', num=3, coin_type='silver', total_coin=10000)
        self.assertEqual(normalize('room', 'gift', gift, '123')['amount'], 0)
        gift.update(coin_type='gold', total_coin=900, price=5000)
        self.assertEqual(normalize('room', 'gift', gift, '123')['amount'], 900)
        guard = dict(uid=42, username='Alice', guard_level=3, num=2, price=198000, start_time=self.now)
        one = normalize('room', 'guard', guard, '123')
        two = normalize('room', 'guard', dict(guard, source=0), '123')
        self.assertEqual(one['id'], two['id'])
        self.assertEqual(one['amount'], 396000)
        self.assertIsNone(normalize('room', 'guard', dict(guard, source=2), '123'))
        official = dict(msg_id='g', open_id='abc', uname='Alice', gift_num=2, price=1000, r_price=800, paid=True,
                        blind_gift={'status': True})
        event = normalize('blivechat', 'gift', official, '123')
        self.assertEqual(event['amount'], 1600)
        self.assertEqual(event['note'], 'blind_value')

    def test_conversion_and_language(self):
        self.assertEqual([batteries(x) for x in (0, 100, 150, 1010)], ['0', '1', '1.5', '10.1'])
        self.assertEqual(language('system', 'ja_JP'), 'ja')
        self.assertEqual(language('system', 'en_US'), 'zh')
        self.assertEqual(language('zh', 'ja_JP'), 'zh')

    def test_official_requires_own_application_credentials(self):
        import queue
        c = Collector(queue.Queue())
        with self.assertRaises(ValueError): c.start('open', auth='TESTCODE')
        self.assertFalse(c.running)

    def test_processed_grouping_keeps_time_order(self):
        rows = [dict(id='a', ts=1, mark='circle', sunk=1), dict(id='b', ts=2, mark='triangle', sunk=0),
                dict(id='c', ts=3, mark='', sunk=0), dict(id='d', ts=4, mark='circle', sunk=1)]
        self.assertEqual([r['id'] if r else None for r in grouped_sc(rows, True)], ['b', 'c', None, 'a', 'd'])
        self.assertEqual([r['id'] for r in grouped_sc(rows, False)], ['a', 'b', 'c', 'd'])
        self.assertNotIn(None, grouped_sc([rows[0], rows[3]], True))


if __name__ == '__main__':
    unittest.main()
