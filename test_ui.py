import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App


class WindowTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).parent / '.test-data'
        folder.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.defaults_patch = patch('config.load_defaults',return_value={})
        self.defaults_patch.start()
        self.overlay_patch = patch('app.Overlay')
        self.overlay_patch.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, Path(self.temp.name), demo=True)

    def tearDown(self):
        self.app.close()
        self.overlay_patch.stop()
        self.defaults_patch.stop()
        self.temp.cleanup()

    def test_languages_and_marking(self):
        a = self.app
        self.assertEqual(a.rank_scope.get(), 'session')
        self.assertFalse(a.video.get())
        self.root.update()
        self.assertEqual(len(a.sc_tree.get_children()), 3)
        a.sc_tree.selection_set('DEMO:room:sc:demo-0')
        a.set_mark('circle')
        self.assertEqual(a.ledger.pending(), 1)
        a.set_mark('circle')
        self.assertEqual(a.ledger.pending(), 2)
        a.set_mark('triangle')
        self.assertEqual(a.ledger.db.execute('SELECT mark FROM events WHERE id=?', ('DEMO:room:sc:demo-0',)).fetchone()[0], 'triangle')
        a.set_mark('circle')
        self.assertEqual(a.ledger.pending(), 1)
        a.change_language('ja')
        self.root.update()
        self.assertIn('SC丸', self.root.title())
        self.assertEqual(a.ledger.pending(), 1)

    def test_mouse_mark_transitions(self):
        from types import SimpleNamespace
        a = self.app
        item = 'DEMO:room:sc:demo-0'
        a.sc_tree.identify_region = lambda x, y: 'cell'
        a.sc_tree.identify_row = lambda y: item
        event = SimpleNamespace(x=10, y=10)
        for click, expected in [('circle', 'circle'), ('circle', ''), ('triangle', 'triangle'),
                                ('circle', 'circle'), ('triangle', 'triangle'), ('triangle', '')]:
            self.assertEqual(a.click_mark(event, click), 'break')
            self.assertEqual(a.ledger.db.execute('SELECT mark FROM events WHERE id=?', (item,)).fetchone()[0], expected)
        a.sc_tree.identify_region = lambda x, y: 'heading'
        self.assertIsNone(a.click_mark(event, 'circle'))
        self.assertEqual(a.ledger.db.execute('SELECT mark FROM events WHERE id=?', (item,)).fetchone()[0], '')

    def test_reset_confirmation_and_recovery(self):
        a = self.app
        with patch('app.messagebox.askyesno', return_value=False): a.reset()
        self.assertEqual(a.ledger.pending(), 2)
        with patch('app.messagebox.askyesno', return_value=True): a.reset()
        self.assertEqual(a.ledger.pending(), 0)
        aid = a.ledger.db.execute('SELECT id FROM archives ORDER BY created DESC LIMIT 1').fetchone()[0]
        a.ledger.restore(aid)
        self.assertEqual(a.ledger.pending(), 2)
        self.assertEqual(sum(r['total'] for r in a.ledger.rankings('DEMO', 'room', daily=False)), 230000)

    def test_disconnect_cancels_automatic_reset(self):
        a = self.app
        a.seen_live = True
        a.auto_reset.set(True)
        a.handle('live', dict(live=False))
        self.assertIsNotNone(a.offline_deadline)
        a.handle('reconnecting', None)
        self.assertIsNone(a.offline_deadline)
        self.assertEqual(a.ledger.pending(), 2)

    def test_processed_toggle_and_noninteractive_divider(self):
        from types import SimpleNamespace
        a = self.app
        a.change_grouping()
        self.assertEqual(a.sc_tree.get_children(), ('DEMO:room:sc:demo-0', 'DEMO:room:sc:demo-2',
                                                    '__processed_separator__', 'DEMO:room:sc:demo-1'))
        a.sc_tree.identify_region = lambda x, y: 'cell'
        a.sc_tree.identify_row = lambda y: '__processed_separator__'
        self.assertEqual(a.click_mark(SimpleNamespace(x=10, y=10), 'circle'), 'break')
        self.assertEqual(a.ledger.pending(), 2)
        # Newly confirmed items remain above the divider until the next button click.
        a.ledger.mark('DEMO:room:sc:demo-0', 'circle')
        a.render()
        self.assertEqual(a.sc_tree.get_children()[0], 'DEMO:room:sc:demo-0')
        a.change_grouping()
        self.assertEqual(a.sc_tree.get_children(), ('DEMO:room:sc:demo-2', '__processed_separator__',
                                                    'DEMO:room:sc:demo-0', 'DEMO:room:sc:demo-1'))

    def test_three_kotobalive_themes_keep_data_and_preferences(self):
        a = self.app
        for theme, expected in [('black', '#1c1b20'), ('white', '#f2efeb'), ('pink', '#f1e3e9')]:
            a.change_theme(theme)
            self.root.update()
            self.assertEqual(self.root.cget('background'), expected)
            self.assertEqual(a.ledger.get('theme'), theme)
            self.assertEqual(a.ledger.pending(), 2)
            self.assertEqual(a.sc_tree.tag_configure('divider')['background'], a.palette['surface'])
            self.assertEqual(a.detail.cget('background'), a.palette['input'])

    def test_content_copies_bv_without_changing_mark(self):
        from types import SimpleNamespace
        a = self.app
        event = SimpleNamespace(x=10, y=10, item_id='DEMO:room:sc:demo-0', column_id='#4')
        with patch.object(self.root, 'clipboard_clear'), patch.object(self.root, 'clipboard_append') as copy:
            a.click_mark(event, 'circle')
            copy.assert_called_once_with('BV1UT42167xb')
        self.assertEqual(a.ledger.db.execute('SELECT mark FROM events WHERE id=?', (event.item_id,)).fetchone()[0], '')
        self.assertIn('BV1UT42167xb', a.notice.get())
        self.assertIn('已复制', a.notice.get())

    def test_settings_can_close_and_json_autosaves(self):
        import json
        a = self.app
        a.open_settings()
        self.assertTrue(a.settings_window.winfo_exists())
        a.room.set('12345')
        a.template.set('Pending: {pending}')
        a.auto_save()
        cfg = json.loads((Path(self.temp.name) / 'config.json').read_text(encoding='utf-8'))
        self.assertEqual(cfg['room'], '12345')
        self.assertEqual(cfg['template'], 'Pending: {pending}')
        with patch.object(a.collector, 'stop') as stop:
            a.close_settings()
            stop.assert_not_called()
        self.assertIsNone(a.settings_window)

    def test_header_uses_anchor_name_and_active_mode(self):
        a = self.app
        a.handle('room', dict(room='22603245', source='room', info=dict(live=False), anchor_name='主播名字'))
        a.handle('heartbeat', None)
        a.render()
        header = a.status_label.cget('text')
        self.assertIn('主播名字', header)
        self.assertIn('直播间 ID 模式', header)
        self.assertNotIn('22603245', header)
        a.handle('room', dict(room='999', source='open', info=dict(live=False)))
        a.handle('heartbeat', None)
        a.render()
        header = a.status_label.cget('text')
        self.assertIn('官方身份码模式', header)
        self.assertIn('主播昵称暂不可用', header)
        self.assertNotIn('主播名字', header)

    def test_three_step_welcome_and_skippable_inline_login(self):
        a = self.app
        with patch('login.QRLogin'):
            a.open_start_page()
            wizard = a.start_page
            self.assertIsNotNone(wizard.qr_panel)
            self.assertFalse(hasattr(wizard, 'role'))
            wizard.skip()
            self.assertEqual(wizard.step, 1)
            wizard.next()
            self.assertEqual(wizard.step, 1)
            a.room.set('22603245')
            wizard.next()
            self.assertEqual(wizard.step, 2)
            wizard.finish(False)
        self.assertEqual(a.mode.get(), 'room')
        self.assertEqual(a.room.get(), '22603245')
        self.assertTrue(a.ledger.get('welcome_seen'))

    def test_reminders_defaults_changes_and_independent_dismissal(self):
        a = self.app
        self.assertTrue(a.reminder_vars['water'][0].get())
        self.assertEqual(float(a.reminder_vars['water'][1].get()), 10)
        self.assertTrue(a.reminder_vars['activity'][0].get())
        self.assertEqual(float(a.reminder_vars['activity'][1].get()), 60)
        a.status = 'connected'
        a.reminders.elapsed = dict(water=600, activity=3600)
        a.update_reminders()
        self.assertEqual(a.reminder_buttons['water'].winfo_manager(), 'pack')
        a.dismiss_reminder('water')
        self.assertEqual(a.reminder_buttons['water'].winfo_manager(), '')
        self.assertEqual(a.reminder_buttons['activity'].winfo_manager(), 'pack')
        a.reminder_vars['water'][1].set('2.5')
        a.reminder_vars['activity'][0].set(False)
        a.save_settings()
        self.assertEqual(a.ledger.get('reminders')['water']['minutes'], 2.5)
        self.assertFalse(a.ledger.get('reminders')['activity']['enabled'])
        self.assertEqual(a.reminder_buttons['activity'].winfo_manager(), '')

    def test_blue_marker_bulk_visibility_and_row_background(self):
        from types import SimpleNamespace
        a = self.app
        self.root.update()
        self.assertEqual(a.confirm_blue_btn.winfo_manager(), '')
        item = 'DEMO:room:sc:demo-0'
        a.sc_tree.selection_set(item)
        normal = a.sc_tree._records[item]['bg']
        a.sc_tree._mouse(SimpleNamespace(), '<Button-2>', item, '#0')
        self.assertEqual(a.ledger.db.execute('SELECT mark FROM events WHERE id=?', (item,)).fetchone()[0], 'square')
        self.assertNotEqual(a.sc_tree._records[item]['bg'], normal)
        self.assertEqual(a.ledger.pending(), 2)
        a.confirm_blue()
        self.assertEqual(a.ledger.pending(), 2)  # Hidden bulk action is also guarded.
        a.video.set(True)
        self.assertEqual(a.confirm_blue_btn.winfo_manager(), 'pack')
        self.assertEqual(a.confirm_blue_btn.cget('text'), '')
        self.assertTrue(a.confirm_blue_btn.cget('image'))
        self.assertEqual(a.blue_confirm_icon.width(), 72)
        a.confirm_blue()
        self.assertEqual(a.ledger.pending(), 1)
        self.assertEqual(a.sc_tree._records[item]['bg'], normal)
        a.video.set(False)
        self.assertEqual(a.confirm_blue_btn.winfo_manager(), '')

    def test_hover_help_can_open_and_close(self):
        a = self.app
        a.confirm_blue_btn.help_bubble.show()
        self.assertTrue(a.confirm_blue_btn.help_bubble.window.winfo_exists())
        a.confirm_blue_btn.help_bubble.hide()
        self.assertIsNone(a.confirm_blue_btn.help_bubble.window)

    def test_middle_click_only_marks_left_cell_and_toggles(self):
        from types import SimpleNamespace
        a = self.app
        item = 'DEMO:room:sc:demo-0'
        self.assertIn('<Button-2>', a.sc_tree._callbacks)
        self.assertTrue(a.sc_tree._records[item]['labels'][0].bind('<Button-2>'))
        def mark(): return a.ledger.db.execute('SELECT mark FROM events WHERE id=?', (item,)).fetchone()[0]
        for action, expected in [('square', 'square'), ('square', ''), ('circle', 'circle'),
                                 ('square', 'square'), ('triangle', 'triangle'), ('square', 'square')]:
            a.click_mark(SimpleNamespace(item_id=item, column_id='#0'), action)
            self.assertEqual(mark(), expected)
        with patch.object(self.root, 'clipboard_clear') as clear:
            a.sc_tree._mouse(SimpleNamespace(), '<Button-2>', item, '#4')
            self.assertEqual(mark(), 'square')
            clear.assert_not_called()

    def test_mark_names_are_localized_for_other_and_processed(self):
        from types import SimpleNamespace
        a = self.app
        item = 'DEMO:room:sc:demo-0'
        a.click_mark(SimpleNamespace(item_id=item, column_id='#0'), 'square')
        self.assertEqual(a.sc_tree._records[item]['text'], '其它')
        a.change_language('ja')
        self.assertEqual(a.sc_tree._records[item]['text'], 'その他')
        a.click_mark(SimpleNamespace(item_id=item, column_id='#0'), 'circle')
        self.assertEqual(a.sc_tree._records[item]['text'], '対応済み')

    def test_optional_login_is_applied_to_room_connection(self):
        a = self.app
        a.demo = False
        a.room.set('22603245')
        a.save_login('test-cookie-only')
        with patch.object(a.collector, 'start') as start:
            a.connect()
            self.assertEqual(start.call_args.kwargs['session_cookie'], 'test-cookie-only')
        a.logout()
        with patch.object(a.collector, 'start') as start:
            a.connect()
            self.assertEqual(start.call_args.kwargs['session_cookie'], '')

    def test_expired_login_popup_is_skippable_and_stale_checks_are_ignored(self):
        a=self.app
        a.ledger.set('welcome_seen',True)
        a.save_login('synthetic-cookie')
        with patch('login.check_saved_session') as check:
            a.startup()
            check.assert_called_once()
        generation=a.login_generation
        with patch.object(a,'open_qr_login') as prompt:
            a.handle('login_checked',dict(generation=generation,valid=None))
            prompt.assert_not_called()
            self.assertTrue(a.session_cookie.get())
            a.handle('login_checked',dict(generation=generation,valid=False))
            prompt.assert_called_once_with(expired=True)
        self.assertTrue(a.login_expired)
        self.assertEqual(a.session_cookie.get(),'')
        a.save_login('replacement-cookie')
        a.handle('login_checked',dict(generation=generation,valid=False))
        self.assertEqual(a.session_cookie.get(),'replacement-cookie')
        self.assertFalse(a.login_expired)

    def test_translation_preserves_original_italic_and_bv_copy_source(self):
        from translation import fingerprint
        a=self.app
        item='DEMO:room:sc:demo-0'
        with patch('app.TranslationWorker'):
            a.translation_enabled.set(True)
            if a.translation_timer: self.root.after_cancel(a.translation_timer)
            a.translation_timer=None
            row=a.ledger.db.execute('SELECT * FROM events WHERE id=?',(item,)).fetchone()
            key=(item,row['text'],fingerprint(a.translation_config()))
            a.translation_cache[key]=dict(text='日本語の翻訳 BV1GJ411x7h7',engine='API',target='ja')
            a.sc_tree.selection_set(item)
            a.select_sc()
        shown=a.detail.get('1.0','end')
        self.assertIn(row['text'],shown)
        self.assertIn('日本語の翻訳',shown)
        self.assertTrue(a.detail.tag_ranges('translation'))
        with patch.object(self.root,'clipboard_clear'),patch.object(self.root,'clipboard_append') as copy:
            a.copy_sc_bv(item)
            copy.assert_called_once_with('BV1UT42167xb')

    def test_hide_original_requires_a_usable_translation(self):
        from translation import fingerprint
        a=self.app
        item='DEMO:room:sc:demo-0'
        with patch('app.TranslationWorker'):
            a.translation_enabled.set(True)
            self.root.after_cancel(a.translation_timer)
            a.translation_timer=None
            row=a.ledger.db.execute('SELECT * FROM events WHERE id=?',(item,)).fetchone()
            key=(item,row['text'],fingerprint(a.translation_config()))
            a.sc_tree.selection_set(item)
            a.hide_original.set(True)
            for result in (dict(text=row['text'],skipped=True),dict(error='translation_api_unavailable'),dict(text='')):
                a.translation_cache[key]=result
                a.select_sc()
                self.assertIn(row['text'],a.detail.get('1.0','end'))
            a.ja_to_zh.set(True)
            self.root.after_cancel(a.translation_timer)
            a.translation_timer=None
            key=(item,row['text'],fingerprint(a.translation_config()))
            a.translation_cache[key]=dict(text='想一起看这个视频',engine='API',target='zh-CN')
            a.select_sc()
            shown=a.detail.get('1.0','end')
            self.assertIn('Mika',shown)
            self.assertIn('想一起看这个视频',shown)
            self.assertNotIn(row['text'],shown)
            a.translation_enabled.set(False)
            self.assertIn(row['text'],a.detail.get('1.0','end'))
            self.assertTrue(a.hide_original_btn.instate(['disabled','!selected']))
            self.assertTrue(a.hide_original.get())
            a.translation_enabled.set(True)
            self.assertTrue(a.hide_original_btn.instate(['!disabled','selected']))
            a.save_settings()
            self.assertTrue(a.ledger.get('translation')['hide_original'])

    def test_interface_font_scale_preserves_italic_and_uses_simhei_fallback(self):
        import tkinter.font as tkfont
        from appearance import resolve_family
        a=self.app
        a.ui_family.set('not-an-installed-font')
        a.ui_scale.set(1.25)
        a.apply_appearance()
        family=resolve_family(self.root,a.ui_family.get())
        self.assertIn(family.lower(),('simhei','黑体'))
        font=tkfont.Font(root=self.root,font=a.detail.tag_cget('translation','font'))
        self.assertEqual(font.actual()['slant'],'italic')
        self.assertEqual(font.actual()['size'],14)
        a.apply_appearance()
        font=tkfont.Font(root=self.root,font=a.detail.tag_cget('translation','font'))
        self.assertEqual(font.actual()['size'],14)  # Reapplying never multiplies the scale.
        a.save_settings()
        self.assertEqual(a.ledger.get('appearance')['scale'],1.25)

    def test_list_translation_is_separate_italic_and_directions_persist(self):
        a=self.app
        self.assertTrue(a.zh_to_ja.get())
        self.assertFalse(a.ja_to_zh.get())
        item='DEMO:room:sc:demo-1'
        with patch('app.TranslationWorker') as worker:
            a.list_translation_enabled.set(True)
            a.render()
            worker.assert_not_called()
            self.assertNotIn('translation_label',a.sc_tree._records[item])
            row=a.ledger.db.execute('SELECT * FROM events WHERE id=?',(item,)).fetchone()
            a.translation_enabled.set(True)
            self.root.after_cancel(a.translation_timer)
            a.translation_timer=None
            a.sc_tree.selection_set(item)
            a.select_sc()
            worker.return_value.start.assert_called_once()
            a.handle('translation',dict(token=a.translation_token,
                result=dict(text='今日もお疲れさまです',engine='API',target='ja')))
            self.assertTrue(a.render_dirty)
            a.render()
            translated=a.sc_tree._records[item]['translation_label']
            self.assertEqual(translated.cget('text'),'今日もお疲れさまです')
            self.assertEqual(a.sc_tree._records[item]['values'][-1],row['text'])
            a.list_translation_enabled.set(False)
            a.render()
            self.assertNotIn('translation_label',a.sc_tree._records[item])
            a.list_translation_enabled.set(True)
            a.render()
            self.assertIn('translation_label',a.sc_tree._records[item])
            worker.return_value.start.assert_called_once()
        a.save_settings()
        self.assertTrue(a.ledger.get('translation')['zh_to_ja'])
        self.assertFalse(a.ledger.get('translation')['ja_to_zh'])

    def test_settings_visual_page_scrolls_and_mode_selector_is_removed(self):
        from tkinter import ttk
        a=self.app
        a.open_settings()
        self.assertIsNone(a.mode_box)
        def find(widget):
            for child in widget.winfo_children():
                if isinstance(child,ttk.Notebook): return child
                found=find(child)
                if found: return found
        notebook=find(a.settings_window)
        notebook.select(1)
        self.root.update()
        page=notebook.nametowidget(notebook.tabs()[1])
        self.assertGreater(page.content.winfo_reqheight(),page.canvas.winfo_height())
        page.canvas.yview_moveto(1)
        self.assertGreater(page.canvas.yview()[0],0)

    def test_user_search_matches_hanzi_pinyin_and_status(self):
        a=self.app
        a.user_search.set('xiaoxia')
        a.render()
        self.assertEqual(a.sc_tree.get_children(),('DEMO:room:sc:demo-1',))
        a.user_search.set('小夏')
        a.set_filter('circle');a.render()
        self.assertEqual(a.sc_tree.get_children(),('DEMO:room:sc:demo-1',))
        a.set_filter('triangle');a.render()
        self.assertFalse(a.sc_tree.get_children())
        a.user_search.set('');a.set_filter('all');a.render()
        self.assertEqual(len(a.sc_tree.get_children()),3)

    def test_open_txt_directory_uses_actual_data_directory(self):
        a=self.app
        with patch('app.os.startfile') as open_folder:
            a.open_exports()
            open_folder.assert_called_once_with(str((Path(self.temp.name)/'exports').resolve()))
        self.assertTrue(a.ledger.export_directory.is_dir())

    def test_stream_end_exports_even_when_auto_archive_disabled_or_enabled(self):
        import time
        a=self.app
        for enabled in (False,True):
            a.auto_reset.set(enabled)
            a.seen_live=True;a.ended=False
            a.offline_deadline=time.monotonic()-1
            a.tick()
            files=list(a.ledger.export_directory.glob('*.txt'))
            self.assertTrue(files)
            saved=files[0].read_text(encoding='utf-8-sig')
            self.assertIn('BV1UT42167xb',saved)
            self.assertIn('小夏',saved)
            self.assertTrue(a.ended)

    def test_exit_flushes_queued_sc_before_final_txt(self):
        import time
        from core import normalize
        a=self.app
        event=normalize('room','sc',dict(id='last-queued',uid=44,uname='CloseTest',message='QUEUED_BEFORE_CLOSE',price=30,start_time=int(time.time())),'DEMO')
        a.queue.put(('event',event))
        a.close()
        saved='\n'.join(p.read_text(encoding='utf-8-sig') for p in (Path(self.temp.name)/'exports').glob('*.txt'))
        self.assertIn('QUEUED_BEFORE_CLOSE',saved)
        self.root=tk.Tk();self.root.withdraw()
        self.app=App(self.root,Path(self.temp.name),demo=True)

    def test_layout_dimensions_survive_rebuild(self):
        a = self.app
        self.root.deiconify()
        self.root.update()
        self.root.geometry('1100x850+40+40')
        self.root.update()
        a.panes.sashpos(0, int(a.panes.winfo_width() * .68))
        a.sc_tree.column('user', width=145)
        a.layout_vars['sc_row_height'].set(80)
        a.layout_vars['list_font_size'].set(12)
        a.save_settings()
        saved = a.ledger.get('layout')
        self.assertTrue(saved['geometry'].startswith('1100x850'))
        self.assertAlmostEqual(saved['split'], .68, places=2)
        self.assertEqual(saved['sc_columns']['user'], 145)
        self.assertEqual(saved['sc_row_height'], 80)
        self.assertEqual(saved['list_font_size'], 12)
        a.change_language('ja')
        self.root.update()
        self.assertEqual(a.sc_tree.widths[2], 145)
        self.assertEqual(a.sc_tree.row_height, 80)
        self.assertAlmostEqual(a.panes.sashpos(0) / a.panes.winfo_width(), .68, places=2)

    def test_preferences_survive_full_restart_but_reminder_progress_does_not(self):
        a = self.app
        a.room.set('22603245')
        a.show_start_page.set(False)
        a.ledger.set('welcome_seen', True)
        a.video.set(True)
        a.auto_reset.set(True)
        a.filter.set('square')
        a.rank_scope.set('day')
        a.change_language('ja')
        a.change_theme('black')
        a.template.set('TEST {pending}')
        a.overlay_font.set('Noto Sans JP')
        a.overlay_size.set(48)
        a.overlay_color = '#aabbcc'
        a.overlay_effects['weight'].set(750)
        a.overlay_effects['glow_enabled'].set(True)
        a.layout_vars['sc_row_height'].set(90)
        a.layout_vars['list_font_size'].set(12)
        a.settings_tab = 2
        a.reminder_vars['water'][0].set(False)
        a.reminder_vars['water'][1].set('13.5')
        a.reminder_vars['activity'][1].set('40')
        a.translation_enabled.set(True)
        a.translation_mode.set('api_only')
        a.translation_key.set('synthetic-api-secret')
        a.sound_enabled.set(False)
        a.sc_sound.set(False)
        a.sound_volume.set(17)
        a.reminders.elapsed = dict(water=600, activity=3600)
        a.save_settings()
        a.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, Path(self.temp.name), demo=True)
        b = self.app
        self.assertEqual(b.room.get(), '22603245')
        self.assertFalse(b.show_start_page.get())
        self.assertTrue(b.video.get())
        self.assertTrue(b.auto_reset.get())
        self.assertEqual((b.lang_choice, b.theme, b.filter.get(), b.rank_scope.get()), ('ja', 'black', 'square', 'day'))
        self.assertEqual((b.template.get(), b.overlay_font.get(), b.overlay_size.get(), b.overlay_color), ('TEST {pending}', 'Noto Sans JP', 48, '#aabbcc'))
        self.assertEqual(b.overlay_effects['weight'].get(), 750)
        self.assertTrue(b.overlay_effects['glow_enabled'].get())
        self.assertEqual(b.layout_vars['sc_row_height'].get(), 90)
        self.assertEqual(b.layout_vars['list_font_size'].get(), 12)
        self.assertEqual(b.settings_tab, 2)
        self.assertFalse(b.reminder_vars['water'][0].get())
        self.assertEqual(float(b.reminder_vars['water'][1].get()), 13.5)
        self.assertEqual(float(b.reminder_vars['activity'][1].get()), 40)
        self.assertEqual(b.reminders.elapsed, dict(water=0, activity=0))
        self.assertIsNone(b.reminders.last)
        self.assertEqual(b.status, 'disconnected')
        self.assertTrue(all(not button.winfo_manager() for button in b.reminder_buttons.values()))
        self.assertTrue(b.translation_enabled.get())
        self.assertEqual(b.translation_mode.get(),'api_only')
        self.assertEqual(b.translation_key.get(),'synthetic-api-secret')
        self.assertNotIn('synthetic-api-secret',(Path(self.temp.name)/'config.json').read_text(encoding='utf-8'))
        self.assertFalse(b.sound_enabled.get())
        self.assertFalse(b.sc_sound.get())
        self.assertEqual(b.sound_volume.get(),17)

    def test_welcome_is_not_automatically_shown_after_first_view(self):
        a = self.app
        with patch('login.QRLogin'):
            a.open_start_page()
            a.start_page.close()
        self.assertTrue(a.ledger.get('welcome_seen'))
        with patch.object(a,'open_start_page') as open_page:
            a.startup()
            open_page.assert_not_called()
        self.assertIsNone(a.start_page)

    def test_login_and_overlay_effects_are_saved_encrypted(self):
        import json
        a = self.app
        self.assertEqual(a.template.get(), '剩余SC： {pending}')
        a.save_login('unit-cookie-only')
        a.overlay_effects['glow_enabled'].set(True)
        a.overlay_effects['weight'].set(750)
        a.auto_save()
        config_path = Path(self.temp.name) / 'config.json'
        text = config_path.read_text(encoding='utf-8')
        self.assertNotIn('unit-cookie-only', text)
        saved = json.loads(text)
        self.assertTrue(saved['overlay_effects']['glow_enabled'])
        self.assertEqual(saved['overlay_effects']['weight'], 750)
        a.logout()
        self.assertEqual(a.ledger.get('session_cookie_protected'), '')

    def test_settings_can_switch_theme_and_language_with_effect_controls_open(self):
        a = self.app
        errors = []
        self.root.report_callback_exception = lambda *args: errors.append(args)
        a.open_settings()
        a.settings_tab = 1
        a.build_settings()
        a.change_theme('black')
        self.root.update()
        a.change_language('ja')
        self.root.update()
        self.assertEqual(errors, [])
        self.assertTrue(a.settings_window.winfo_exists())


if __name__ == '__main__': unittest.main()
