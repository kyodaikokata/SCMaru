import unittest
from user_search import matches_user


class SearchTests(unittest.TestCase):
    def test_hanzi_full_pinyin_initials_and_partial_words(self):
        for query in ('峰踏','fengta','feng ta chang lu','ftcl','FĒNG TÀ','changlu'):
            self.assertTrue(matches_user('峰踏长路',query),query)
        self.assertFalse(matches_user('峰踏长路','mika'))
        self.assertTrue(matches_user('Mika_小夏','MIKA'))
        self.assertTrue(matches_user('Mika_小夏','xiaoxia'))
        self.assertTrue(matches_user('Mika_小夏','xx'))
        self.assertTrue(matches_user('小夏',''))
