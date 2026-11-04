"""Synthetic QR content only: never automate a user's authentication dialog."""
import unittest
import tkinter as tk
from unittest.mock import patch, Mock

from login import LoginDialog, qr_matrix, matrix_photo
from i18n import translate
from themes import PALETTES


class QRDisplayTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.worker = patch('login.QRLogin').start()
        self.callback = Mock()
        self.dialog = LoginDialog(self.root, translate, PALETTES['pink'], self.callback)

    def tearDown(self):
        self.dialog.close()
        patch.stopall()
        self.root.update_idletasks()
        self.root.destroy()

    def drain(self):
        if self.dialog.timer: self.dialog.panel.after_cancel(self.dialog.timer)
        self.dialog.poll()

    def test_native_matrix_renders_crisp_white_quiet_zone_and_black_modules(self):
        matrix = qr_matrix('SCMaru synthetic QR rendering test')
        self.dialog.queue.put(('matrix', matrix))
        self.dialog.queue.put(('status', 'qr_waiting'))
        self.drain()
        photo = self.dialog.photo
        self.assertIsNotNone(photo)
        self.assertEqual(photo.width(), photo.height())
        self.assertLessEqual(photo.width(), 280)
        self.assertEqual(photo.width() % len(matrix), 0)
        self.assertEqual(photo.get(0, 0), (255, 255, 255))
        scale = photo.width() // len(matrix)
        self.assertEqual(photo.get(4 * scale, 4 * scale), (0, 0, 0))
        self.assertEqual(self.dialog.status.get(), translate('qr_waiting'))

    def test_render_failure_is_visible_and_refresh_can_recover(self):
        self.dialog.queue.put(('matrix', [[True]]))
        self.drain()
        self.assertEqual(self.dialog.status.get(), translate('qr_render_failed'))
        old_queue = self.dialog.queue
        self.dialog.refresh()
        self.assertIsNot(old_queue, self.dialog.queue)
        old_queue.put(('failure', dict(stage='qr_stage_generate', reason='qr_network_error', code=None)))
        self.dialog.queue.put(('matrix', qr_matrix('refreshed synthetic QR')))
        self.drain()
        self.assertIsNotNone(self.dialog.photo)
        self.assertNotIn(translate('qr_network_error'), self.dialog.status.get())

    def test_network_and_api_failures_are_explained_without_request_urls(self):
        self.dialog.queue.put(('failure', dict(stage='qr_stage_generate', reason='qr_http_error', code=503)))
        self.drain()
        self.assertIn('503', self.dialog.status.get())
        self.assertIn(translate('qr_stage_generate'), self.dialog.status.get())
        self.assertIn(translate('qr_http_error'), self.dialog.status.get())

    def test_success_callback_fires_once_and_refresh_cancels_old_success_timer(self):
        self.dialog.queue.put(('success', 'synthetic-cookie'))
        self.drain()
        self.callback.assert_called_once_with('synthetic-cookie')
        timer = self.dialog.success_timer
        self.dialog.refresh()
        self.assertIsNone(self.dialog.success_timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))

    def test_bad_matrix_rejected(self):
        with self.assertRaises(ValueError): matrix_photo(self.root, [[True]])
