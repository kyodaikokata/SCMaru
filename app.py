from __future__ import annotations

import argparse
import ctypes
from collections import OrderedDict
import locale
import logging
import os
from pathlib import Path
import queue
import sys
from threading import Thread
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk, colorchooser
from datetime import datetime

from core import Ledger, batteries, language, normalize, grouped_sc, BV
from config import protect, unprotect
from connections import Collector
from i18n import translate
from overlay import Overlay, EFFECTS, normalize_effects
from themes import PALETTES
from sc_list import SCList
from reminders import Reminders, minutes
from tooltip import Tooltip
from version import VERSION
from data_location import data_directory
from notifications import ReminderBadge, SoundPlayer
from translation import TranslationWorker, fingerprint
from scroll_page import ScrollPage
from appearance import apply_widgets,resolve_family
from user_search import matches_user, variants
from txt_archive import import_file
import updater


def system_language():
    if sys.platform == 'win32':
        return locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), 'zh_CN')
    return locale.getlocale()[0] or 'zh_CN'


def status_icon(master, shape, color=None):
    """Draw consistent green circle/yellow triangle without system emoji fonts."""
    import math
    image = tk.PhotoImage(master=master, width=24, height=24)
    points = ((12, 3), (22, 21), (2, 21))
    for y in range(24):
        for x in range(24):
            hit = abs(math.hypot(x - 12, y - 12) - 8) < 1.5 if shape == 'circle' else False
            if shape == 'triangle':
                for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
                    dx, dy = bx - ax, by - ay
                    u = max(0, min(1, ((x-ax)*dx + (y-ay)*dy) / (dx*dx + dy*dy)))
                    hit |= math.hypot(x-ax-u*dx, y-ay-u*dy) < 1.3
            if shape == 'square':
                hit = 4 <= x <= 20 and 4 <= y <= 20 and (x <= 6 or x >= 18 or y <= 6 or y >= 18)
            if hit:
                image.put(color or ('#35b778' if shape == 'circle' else '#e5bd47'), (x, y))
    return image


def blue_to_green_icon(master, icons, color):
    """Blue square → green circle, independent of locale and emoji fonts."""
    result = tk.PhotoImage(master=master, width=72, height=24)
    result.tk.call(result, 'copy', icons['square'], '-to', 0, 0)
    result.tk.call(result, 'copy', icons['circle'], '-to', 48, 0)
    for x in range(28, 44):
        for y in (11, 12): result.put(color, (x, y))
    for d in range(6):
        for y in (11-d, 12+d): result.put(color, (43-d, y))
    return result


class App:
    def __init__(self, root, directory, demo=False):
        self.root = root
        self.ledger = Ledger(directory)
        self.queue = queue.Queue()
        self.collector = Collector(self.queue)
        self.lang_choice = self.ledger.get('language', 'system')
        if self.lang_choice not in ('system', 'zh', 'ja'): self.lang_choice = 'system'
        self.lang = language(self.lang_choice, system_language())
        self.theme = self.ledger.get('theme', 'pink')
        if self.theme not in PALETTES: self.theme = 'pink'
        appearance=self.ledger.get('appearance',{})
        self.ui_family=tk.StringVar(value=appearance.get('font','Microsoft YaHei UI'))
        self.ui_scale=tk.DoubleVar(value=max(.75,min(1.6,float(appearance.get('scale',1)))))
        self.appearance_timer=None
        self.mode = tk.StringVar(value='room')
        self.layout = self.ledger.get('layout', {})
        if not isinstance(self.layout, dict): self.layout = {}
        self.layout_vars = {key: tk.IntVar(value=max(low, min(high, int(self.layout.get(key, default)))))
                            for key, default, low, high in [('sc_row_height', 62, 40, 160), ('list_font_size', 10, 8, 20),
                                                            ('sc_detail_height', 3, 1, 10), ('rank_detail_height', 5, 1, 10)]}
        self.reminders = Reminders()
        self.reminder_due = set()
        self.sound_player = SoundPlayer(directory)
        sound = self.ledger.get('sound', {})
        self.sound_enabled = tk.BooleanVar(value=sound.get('enabled',True))
        self.sc_sound = tk.BooleanVar(value=sound.get('sc',True))
        self.alarm_sound = tk.BooleanVar(value=sound.get('alarm',True))
        self.sound_volume = tk.DoubleVar(value=sound.get('volume',35))
        trans = self.ledger.get('translation', {})
        self.translation_enabled = tk.BooleanVar(value=trans.get('enabled',False))
        self.auto_translate_new = tk.BooleanVar(value=trans.get('auto_new', False))
        self.hide_original = tk.BooleanVar(value=trans.get('hide_original',False))
        self.list_translation_enabled = tk.BooleanVar(value=trans.get('list_enabled',False))
        self.zh_to_ja = tk.BooleanVar(value=trans.get('zh_to_ja',True))
        self.ja_to_zh = tk.BooleanVar(value=trans.get('ja_to_zh',False))
        self.translation_mode = tk.StringVar(value=trans.get('mode','api_first'))
        if self.translation_mode.get() not in ('api_first','api_only','google_only'): self.translation_mode.set('api_first')
        self.translation_url = tk.StringVar(value=trans.get('url','https://api.deepseek.com'))
        self.translation_model = tk.StringVar(value=trans.get('model','deepseek-flash'))
        self.translation_key = tk.StringVar(value=unprotect(trans.get('key_protected','')))
        self.translation_worker = None
        self.translation_token = 0
        self.translation_cache = {}
        self.translation_current = None
        self.translation_pending = OrderedDict()
        self.translation_timer = None
        saved_reminders = self.ledger.get('reminders', {})
        self.reminder_vars = {}
        for key, default in [('water', 10), ('activity', 60)]:
            saved = saved_reminders.get(key, {})
            self.reminder_vars[key] = (tk.BooleanVar(value=saved.get('enabled', True)),
                                       tk.StringVar(value=str(minutes(saved.get('minutes'), default))))
        self.room = tk.StringVar(value=self.ledger.get('room', ''))
        self.remember_auth = tk.BooleanVar(value=self.ledger.get('remember_auth', False))
        self.auth = tk.StringVar(value=unprotect(self.ledger.get('auth_protected', '')) if self.remember_auth.get() else '')
        self.access_key_id = tk.StringVar(value=os.environ.get('SCDESK_ACCESS_KEY_ID') or unprotect(self.ledger.get('access_key_id_protected', '')))
        self.access_key_secret = tk.StringVar(value=os.environ.get('SCDESK_ACCESS_KEY_SECRET') or unprotect(self.ledger.get('access_key_secret_protected', '')))
        self.app_id = tk.StringVar(value=os.environ.get('SCDESK_APP_ID') or str(self.ledger.get('app_id', '')))
        self.session_cookie = tk.StringVar(value=unprotect(self.ledger.get('session_cookie_protected', '')))
        self.login_expired = bool(self.ledger.get('login_expired', False) or (self.ledger.get('session_cookie_protected') and not self.session_cookie.get()))
        self.login_generation = 0
        self._protected_cache = {}
        self.video = tk.BooleanVar(value=self.ledger.get('video', False))
        self.show_start_page = tk.BooleanVar(value=not self.ledger.get('welcome_seen', False))
        self.auto_reset = tk.BooleanVar(value=self.ledger.get('auto_reset', False))
        template = self.ledger.get('template', '剩余SC： {pending}')
        if template == 'SC: {pending}': template = '剩余SC： {pending}'
        self.template = tk.StringVar(value=template)
        self.overlay_font = tk.StringVar(value=self.ledger.get('overlay_font', 'M PLUS Rounded 1c'))
        self.overlay_size = tk.DoubleVar(value=float(self.ledger.get('overlay_size', 36)))
        self.overlay_color = self.ledger.get('overlay_color', '#ffffff')
        effects = normalize_effects(self.ledger.get('overlay_effects', {}))
        self.overlay_effects = {key: (tk.BooleanVar(value=value) if isinstance(value, bool) else
                                    tk.StringVar(value=value) if isinstance(value, str) else tk.DoubleVar(value=value))
                                for key, value in effects.items()}
        self.filter = tk.StringVar(value=self.ledger.get('filter', 'all'))
        self.user_search = tk.StringVar(value=self.ledger.get('user_search',''))
        self.rank_scope = tk.StringVar(value=self.ledger.get('rank_scope', 'session'))
        self.rank_sort = 'amount'
        self.sc_sort = 'time'
        self.sc_sort_reverse = False
        if self.filter.get() not in ('all', 'pending', 'circle', 'triangle', 'square'): self.filter.set('all')
        if self.rank_scope.get() not in ('day', 'session'): self.rank_scope.set('session')
        self.status = 'disconnected'
        self.status_extra = ''
        self.heartbeat = 0
        self.offline_deadline = None
        self.seen_live = False
        self.ended = False
        self.active_room = self.room.get()
        self.active_source = self.mode.get()
        self.active_anchor = ''
        self.anchor_names = {}
        self.active_logged_in = False
        self.export_dirty = False
        self.render_dirty = True
        self.closing = False
        self.update_busy = False
        self.update_stage = None
        self.txt_seen = {}
        self.demo = demo
        self.main_frame = None
        self.settings_window = None
        self.start_page = None
        self.login_dialog = None
        self.settings_tab = max(0, min(4, int(self.ledger.get('settings_tab', 0))))
        self.input_widgets = []
        self.mode_box = None
        self.save_timer = None
        self.settings_notice = tk.StringVar()
        self.notice = tk.StringVar()
        self.reminder_countdowns = {key: tk.StringVar() for key in ('water','activity')}
        self.overlay = None
        self.overlay_error = ''
        try:
            self.overlay = Overlay()
        except OSError:
            self.overlay_error = '18964 port unavailable'
        self.asset_root = Path(__file__).parent / 'assets'
        self.brand = None
        icon = self.asset_root / 'icon.ico'
        if sys.platform == 'win32' and icon.is_file():
            root.iconbitmap(default=str(icon))
            root.iconbitmap(str(icon))
        if (self.asset_root / 'icon.png').is_file(): self.brand = tk.PhotoImage(master=root, file=str(self.asset_root / 'icon.png')).subsample(8, 8)
        import re
        geometry = self.layout.get('geometry', '1064x832')
        if not isinstance(geometry, str) or not re.fullmatch(r'\d{3,5}x\d{3,5}(?:[+-]-?\d+[+-]-?\d+)?', geometry): geometry = '1064x832'
        root.geometry(geometry)
        if self.layout.get('maximized'): root.state('zoomed')
        root.minsize(940, 600)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.style()
        self.build()
        # Restore the last local capture without initiating any connection.
        row = self.ledger.db.execute(
            "SELECT * FROM sessions WHERE NOT (room='TEST' AND source LIKE 'txt-%') ORDER BY started DESC LIMIT 1"
        ).fetchone()
        if row:
            self.ledger.session = row['id']
            self.active_room, self.active_source = row['room'], row['source']
            self.ended = bool(row['ended'])
        if demo:
            self.load_demo()
        if self.video.get(): self.export_dirty |= bool(self.ledger.classify_video_sc())
        self.render()
        for variable in (self.mode, self.room, self.auth, self.remember_auth, self.access_key_id,
                         self.access_key_secret, self.app_id, self.auto_reset, self.show_start_page,
                         self.template, self.overlay_font, self.overlay_size, self.filter, self.rank_scope,
                         self.session_cookie, *self.overlay_effects.values()):
            variable.trace_add('write', self.schedule_save)
        for variable in (self.sound_enabled,self.sc_sound,self.alarm_sound,self.sound_volume): variable.trace_add('write',self.schedule_save)
        for variable in (self.ui_family,self.ui_scale): variable.trace_add('write',self.change_appearance)
        self.list_translation_enabled.trace_add('write', self.change_list_translation)
        for variable in (self.translation_enabled,self.auto_translate_new,self.zh_to_ja,self.ja_to_zh,self.translation_mode,self.translation_url,self.translation_model,self.translation_key):
            variable.trace_add('write',self.change_translation)
        self.hide_original.trace_add('write',self.change_hide_original)
        for pair in self.reminder_vars.values():
            for variable in pair: variable.trace_add('write', self.reminder_changed)
        for variable in self.layout_vars.values(): variable.trace_add('write', self.change_layout_sizes)
        self.video.trace_add('write', self.change_video_mode)
        self.user_search.trace_add('write',self.change_user_search)
        root.bind('<Configure>', lambda e: self.schedule_save() if e.widget == root else None, add='+')
        self.save_settings()
        self.root.after(200, self.tick)
        if not demo: self.root.after(350, self.startup)

    def startup(self):
        if self.closing: return
        if not self.demo and self.ledger.get('test_archive_checked_version') != VERSION:
            try:
                self.install_test_archive()
                self.ledger.set('test_archive_checked_version', VERSION)
            except (OSError, ValueError) as error:
                self.notice.set(self.t('error') + ': ' + type(error).__name__)
        if not self.ledger.get('welcome_seen', False): self.open_start_page()
        if self.login_expired: self.prompt_expired_login()
        elif self.session_cookie.get():
            from login import check_saved_session
            self.login_generation += 1
            check_saved_session(self.queue, self.session_cookie.get(), self.login_generation)

    def install_test_archive(self):
        folder = self.ledger.export_directory
        for path in folder.glob('*.txt'):
            if 'test' not in path.stem.casefold():
                continue
            try:
                if import_file(self.ledger, path):
                    return
            except (OSError, ValueError, OverflowError):
                continue

        sample = self.asset_root / 'TEST_15_SC.txt'
        content = sample.read_bytes()
        folder.mkdir(parents=True, exist_ok=True)
        index = 1
        while True:
            target = folder / (sample.name if index == 1 else f'{sample.stem}_{index}.txt')
            try:
                output = target.open('xb')
                break
            except FileExistsError:
                index += 1
        try:
            with output:
                output.write(content)
        except OSError:
            target.unlink(missing_ok=True)
            raise

    def prompt_expired_login(self):
        if self.start_page and self.start_page.window.winfo_exists(): self.start_page.show_expired()
        else: self.open_qr_login(expired=True)

    def t(self, key, **kw):
        return translate(key, self.lang, **kw)

    def style(self):
        p = self.palette = PALETTES[self.theme]
        colors = dict(circle='#74c895' if self.theme == 'black' else '#278654', triangle='#e5bd47' if self.theme == 'black' else '#b98a16', square='#78a8df' if self.theme == 'black' else '#3376b9')
        self.icons = {key: status_icon(self.root, key, color) for key, color in colors.items()}
        self.blue_confirm_icon = blue_to_green_icon(self.root, self.icons, p['fg'])
        self.root.configure(bg=p['bg'])
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', background=p['bg'], foreground=p['fg'], font=('Microsoft YaHei UI', 10), bordercolor=p['line'])
        style.configure('TFrame', background=p['bg'])
        style.configure('TLabel', background=p['bg'], foreground=p['fg'])
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'))
        style.configure('Count.TLabel', font=('Segoe UI', 15, 'bold'), foreground=p['green'])
        style.configure('Muted.TLabel', foreground=p['muted'])
        style.configure('TButton', padding=(10, 7), background=p['shade'], foreground=p['fg'])
        style.configure('Reminder.TButton', background=p['shade'], foreground=p['fg'])
        style.configure('ReminderPulse.TButton', background=p['accent'], foreground=p['fg'])
        style.map('TButton', background=[('active', p['accent'])], foreground=[('disabled', p['muted'])])
        style.configure('TEntry', fieldbackground=p['input'], foreground=p['fg'], insertcolor=p['fg'], padding=6)
        style.configure('TCombobox', fieldbackground=p['input'], foreground=p['fg'], padding=5)
        style.map('TCombobox', fieldbackground=[('readonly', p['input'])], foreground=[('readonly', p['fg'])])
        style.configure('TSpinbox', fieldbackground=p['input'], foreground=p['fg'], arrowcolor=p['fg'])
        style.configure('Treeview', background=p['panel'], fieldbackground=p['panel'], foreground=p['fg'],
                        rowheight=38, borderwidth=0, font=('Microsoft YaHei UI', self.layout_vars['list_font_size'].get()))
        style.configure('Treeview.Heading', background=p['surface'], foreground=p['fg'], padding=6)
        style.map('Treeview', background=[('selected', p['accent'])], foreground=[('selected', p['fg'])])
        style.configure('TCheckbutton', padding=4, background=p['bg'], foreground=p['fg'])
        style.map('TCheckbutton', background=[('active', p['accent'])])
        style.configure('TScrollbar', background=p['surface'], troughcolor=p['bg'], arrowcolor=p['muted'])
        self.root.option_add('*TCombobox*Listbox.background', p['input'])
        self.root.option_add('*TCombobox*Listbox.foreground', p['fg'])
        family=resolve_family(self.root,self.ui_family.get())
        scale=self.ui_scale.get()
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont','TkTooltipFont'):
            try: tkfont.nametofont(name,root=self.root).configure(family='SimHei')
            except tk.TclError: pass
        style.configure('.',font=(family,round(10*scale)))
        style.configure('Title.TLabel',font=(family,round(16*scale),'bold'))
        style.configure('Count.TLabel',font=(family,round(15*scale),'bold'))
        style.configure('Treeview',font=(family,round(self.layout_vars['list_font_size'].get()*scale)),rowheight=round(38*scale))
        style.configure('TButton',padding=(round(10*scale),round(7*scale)))
        style.configure('Compact.TButton',padding=(round(8*scale),round(3*scale)))
        self.root.option_add('*TCombobox*Listbox.font',(family,round(10*scale)))

    def build(self):
        if self.main_frame is not None: self.capture_layout()
        if self.main_frame is not None: self.main_frame.destroy()
        self.root.title('SCMaru ' + VERSION + ' · ' + self.t('title') + (' [DEMO]' if self.demo else ''))
        outer = ttk.Frame(self.root, padding=(14,8,14,10))
        self.main_frame = outer
        self.rank_signature = None
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        top = ttk.Frame(outer)
        top.grid(row=0, column=0, sticky='ew')
        if self.brand: ttk.Label(top, image=self.brand).pack(side='left', padx=(0, 12))
        ttk.Label(top, text='SC丸 ' + VERSION, style='Title.TLabel').pack(side='left')
        ttk.Label(top, text='スパチャの整理をしましょうね♪', font=('Yu Gothic UI', 12)).pack(side='left', padx=12)
        top_right = ttk.Frame(top)
        top_right.pack(side='right')
        buttons = ttk.Frame(top_right)
        buttons.pack(anchor='e')
        ttk.Button(buttons, text=self.t('settings'), command=self.open_settings,style='Compact.TButton').pack(side='right')
        ttk.Button(buttons, text=self.t('start_page'), command=self.open_start_page,style='Compact.TButton').pack(side='right', padx=6)
        self.status_label = ttk.Label(top_right, style='Muted.TLabel')
        self.status_label.pack(anchor='e', pady=(0, 0))
        form = ttk.Frame(outer, padding=(0, 4, 0, 0))
        form.grid(row=1, column=0, sticky='ew')
        connection=ttk.LabelFrame(form,text=self.t('connection_group'),padding=(6,0))
        connection.pack(side='left',padx=(0,8),fill='y')
        management=ttk.LabelFrame(form,text=self.t('management_group'),padding=(6,0))
        management.pack(side='left',fill='y')
        ttk.Label(connection,text=self.t('room')).pack(side='left',padx=(0,5))
        self.main_room_entry=ttk.Entry(connection,textvariable=self.room,width=12)
        self.main_room_entry.pack(side='left',padx=(0,6))
        self.main_room_entry.bind('<Return>',lambda e:self.connect())
        self.connect_btn=ttk.Button(connection,text=self.t('connect'),command=self.connect,style='Compact.TButton')
        self.connect_btn.pack(side='left')
        self.disconnect_btn=ttk.Button(connection,text=self.t('disconnect'),command=self.disconnect,style='Compact.TButton')
        self.disconnect_btn.pack(side='left',padx=5)
        for key,action in [('reset',self.reset),('history',self.history),('export',self.export_now)]:
            ttk.Button(management,text=self.t(key),command=action,style='Compact.TButton').pack(side='left',padx=3)
        self.open_exports_btn=ttk.Button(management,text=self.t('open_exports'),command=self.open_exports,style='Compact.TButton')
        self.open_exports_btn.pack(side='left',padx=3)
        self.url_copy_btn=ttk.Button(management,text=self.t('copy_url_main'),command=self.copy_overlay,style='Compact.TButton')
        self.url_copy_btn.pack(side='left',padx=3)
        summary = ttk.Frame(outer, padding=(0, 4, 0, 4))
        self.summary=summary
        summary.configure(height=round(46*self.ui_scale.get()))
        summary.pack_propagate(False)
        summary.grid(row=2, column=0, sticky='ew')
        self.count_label = ttk.Label(summary, style='Count.TLabel')
        self.count_label.pack(side='left')
        self.reminder_buttons = {}
        for key in ('water', 'activity'):
            self.reminder_buttons[key] = ReminderBadge(summary, self.t(key+'_hint'), key, self.palette, lambda k=key: self.dismiss_reminder(k))
        self.total_label = ttk.Label(summary)
        self.total_label.pack(side='right')
        panes = ttk.Panedwindow(outer, orient='horizontal')
        panes.grid(row=3, column=0, sticky='nsew')
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        for panel in (left, right):
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(1, weight=1)
        panes.add(left, weight=3)
        panes.add(right, weight=1)
        self.panes = panes
        def place_sash():
            if self.closing or not panes.winfo_exists(): return
            if panes.winfo_width() > 200: panes.sashpos(0, int(panes.winfo_width() * max(.4, min(.88, float(self.layout.get('split', .75))))))
            else: self.root.after(50, place_sash)
        self.root.after_idle(place_sash)
        panes.bind('<ButtonRelease-1>', self.schedule_save, add='+')
        lh = ttk.Frame(left)
        lh.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        list_head=ttk.Frame(lh);list_head.pack(fill='x')
        list_actions=ttk.Frame(lh);list_actions.pack(fill='x',pady=(4,0))
        search_box=ttk.Frame(list_actions)
        search_box.pack(side='right',padx=(8,4))
        ttk.Label(search_box,text=self.t('search_user')).pack(side='left',padx=(0,5))
        self.user_search_entry=self.help(ttk.Entry(search_box,textvariable=self.user_search,width=16),'search_user_help')
        self.user_search_entry.pack(side='left')
        ttk.Button(search_box,text='×',width=2,style='Compact.TButton',command=lambda:self.user_search.set('')).pack(side='left',padx=(4,0))
        ttk.Label(list_head, text=self.t('left'), font=('Segoe UI', 12, 'bold')).pack(side='left')
        self.help(ttk.Checkbutton(list_head, text=self.t('video'), variable=self.video), 'video_help').pack(side='left', padx=5)
        ttk.Checkbutton(list_head,text=self.t('list_translate'),variable=self.list_translation_enabled).pack(side='left',padx=6)
        ttk.Button(list_actions, text=self.t('sort_processed'), command=self.change_grouping,style='Compact.TButton').pack(side='left', padx=0)
        self.sc_sort_label = ttk.Label(list_actions, style='Muted.TLabel')
        self.sc_sort_label.pack(side='left', padx=6)
        self.confirm_blue_btn = self.help(ttk.Button(list_actions, image=self.blue_confirm_icon, command=self.confirm_blue,style='Compact.TButton'), 'confirm_blue_help')
        if self.video.get(): self.confirm_blue_btn.pack(side='left', padx=6)
        filter_box = ttk.Combobox(list_head, state='readonly', values=[self.t(k) for k in ('all', 'pending', 'circle', 'triangle', 'square')], width=10)
        self.filter_box = filter_box
        filter_box.current(('all', 'pending', 'circle', 'triangle', 'square').index(self.filter.get()))
        filter_box.pack(side='right', padx=8)
        filter_box.bind('<<ComboboxSelected>>', lambda e: self.set_filter(('all', 'pending', 'circle', 'triangle', 'square')[filter_box.current()]))
        self.detail_split = ttk.Panedwindow(left,orient='vertical')
        self.detail_split.grid(row=1,column=0,sticky='nsew')
        table_host,detail_host = ttk.Frame(self.detail_split),ttk.Frame(self.detail_split)
        table_host.rowconfigure(1,weight=1);table_host.columnconfigure(0,weight=1)
        detail_host.rowconfigure(2,weight=1);detail_host.columnconfigure(0,weight=1)
        self.detail_split.add(table_host,weight=4)
        self.detail_split.add(detail_host,weight=1)
        def place_detail():
            if self.closing or not self.detail_split.winfo_exists(): return
            height=self.detail_split.winfo_height()
            if height>180: self.detail_split.sashpos(0,max(80,height-max(90,int(self.layout.get('sc_detail_pixels',130)))))
            else: self.root.after(50,place_detail)
        self.root.after_idle(place_detail)
        self.detail_split.bind('<ButtonRelease-1>',self.schedule_save,add='+')
        self.sc_tree = self.tree(table_host, ('time', 'user', 'amount', 'content'), (130, 100, 75, 220), status=True)
        for column in ('time', 'user', 'amount'):
            self.sc_tree.heading(column, text=self.t(column), command=lambda key=column: self.change_sc_sort(key))
        self.sc_tree.bind('<<TreeviewSelect>>', self.select_sc)
        for binding, mark in [('<Button-1>', 'circle'), ('<Double-Button-1>', 'circle'),
                              ('<Button-2>', 'square'), ('<Double-Button-2>', 'square'),
                              ('<Button-3>', 'triangle'), ('<Double-Button-3>', 'triangle')]:
            self.sc_tree.bind(binding, lambda e, m=mark: self.click_mark(e, m))
        self.sc_tree.tag_configure('removed', foreground=self.palette['muted'])
        self.sc_tree.tag_configure('divider', foreground=self.palette['muted'], background=self.palette['surface'], font=('Microsoft YaHei UI', 10, 'bold'))
        self.help(ttk.Label(detail_host, text=self.t('mouse_marks'), style='Muted.TLabel'), 'mark_help').grid(row=0, column=0, sticky='w', pady=3)
        trans_head=ttk.Frame(detail_host)
        trans_head.grid(row=1,column=0,sticky='ew')
        self.help(ttk.Checkbutton(trans_head,text=self.t('translate_sc'),variable=self.translation_enabled),'translation_help').pack(side='left')
        self.help(ttk.Checkbutton(trans_head, text=self.t('auto_translate_new'), variable=self.auto_translate_new),
                  'auto_translate_new_help').pack(side='left', padx=5)
        ttk.Checkbutton(trans_head,text=self.t('zh_to_ja'),variable=self.zh_to_ja).pack(side='left',padx=8)
        ttk.Checkbutton(trans_head,text=self.t('ja_to_zh'),variable=self.ja_to_zh).pack(side='left',padx=8)
        self.hide_original_btn=ttk.Checkbutton(trans_head,text=self.t('hide_original'),variable=self.hide_original)
        self.hide_original_btn.pack(side='left',padx=4)
        self.sync_hide_original()
        ttk.Button(trans_head,text=self.t('translation_retry'),command=self.retry_translation).pack(side='right',padx=8)
        self.detail = tk.Text(detail_host, height=self.layout.get('sc_detail_height', 3), wrap='word', bg=self.palette['input'], fg=self.palette['fg'], relief='flat',
                              font=('Segoe UI', 11), padx=10, pady=8, state='disabled')
        self.detail.grid(row=2, column=0, sticky='nsew', padx=(0, 8))
        self.detail.tag_configure('translation',font=('Segoe UI',11,'italic'))
        self.detail.tag_configure('translation_meta',foreground=self.palette['muted'],font=('Segoe UI',9))
        rh = ttk.Frame(right)
        rh.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        rank_head = ttk.Frame(rh)
        rank_head.pack(fill='x')
        ttk.Label(rank_head, text=self.t('right'), font=('Segoe UI', 12, 'bold')).pack(side='left', padx=8)
        scope = ttk.Combobox(rank_head, values=[self.t('day'), self.t('session')], state='readonly', width=8)
        scope.current(self.rank_scope.get() == 'session')
        scope.pack(side='right')
        scope.bind('<<ComboboxSelected>>', lambda e: self.set_scope(('day', 'session')[scope.current()]))
        rank_actions = ttk.Frame(rh)
        rank_actions.pack(fill='x', pady=(4, 0))
        self.rank_sort_label = ttk.Label(rank_actions, style='Muted.TLabel')
        self.rank_sort_label.pack(side='left', padx=8)
        ttk.Button(rank_actions, text=self.t('switch_sort'), style='Compact.TButton',
                   command=self.change_rank_sort).pack(side='right')
        self.rank_tree = self.tree(right, ('user', 'amount'), (160, 60))
        self.rank_tree.bind('<<TreeviewSelect>>', self.select_rank)
        self.rank_detail = tk.Text(right, height=self.layout.get('rank_detail_height', 5), wrap='word', bg=self.palette['input'], fg=self.palette['fg'], relief='flat',
                                   font=('Segoe UI', 10), padx=10, pady=8, state='disabled')
        self.rank_detail.grid(row=2, column=0, sticky='ew', padx=(8, 0), pady=(8, 0))
        ttk.Label(outer, textvariable=self.notice, style='Muted.TLabel', wraplength=1100).grid(row=4, column=0, sticky='w', pady=(8, 0))
        self.apply_appearance()
        self.render_dirty = True

    def tree(self, parent, columns, widths, status=False):
        box = ttk.Frame(parent)
        box.grid(row=1, column=0, sticky='nsew', padx=(0, 8) if status else (8, 0))
        tree = SCList(box, self.palette) if status else ttk.Treeview(box, columns=columns, show='headings', selectmode='browse')
        if status:
            tree.heading('#0', text='○ / △ / □')
            tree.column('#0', width=120, minwidth=55, stretch=False)
        for key, width in zip(columns, widths):
            tree.heading(key, text=self.t(key))
            tree.column(key, width=width, minwidth=55, stretch=key in ('content', 'user'))
        saved = self.layout.get('sc_columns' if status else 'rank_columns', {})
        for key, width in saved.items():
            if key in (('#0',) + columns if status else columns):
                try: tree.column(key, width=max(55, min(1200, int(width))))
                except (ValueError, TypeError): pass
        if status:
            tree.on_resize = self.schedule_save
            tree.row_height = max(40, min(240, int(self.layout.get('sc_row_height', 62))))
            tree.font_size = self.layout_vars['list_font_size'].get()
        else: tree.bind('<ButtonRelease-1>', self.schedule_save, add='+')
        y = ttk.Scrollbar(box, orient='vertical', command=tree.yview)
        x = ttk.Scrollbar(box, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky='nsew')
        y.grid(row=0, column=1, sticky='ns')
        x.grid(row=1, column=0, sticky='ew')
        return tree

    def build_fields(self):
        for c in self.fields.winfo_children(): c.destroy()
        self.input_widgets = []
        keys = [('room', self.room, 20, False)] if self.mode.get() == 'room' else [('auth', self.auth, 25, True)]
        for label, variable, width, secret in keys:
            ttk.Label(self.fields, text=self.t(label)).pack(side='left', padx=(0, 8))
            entry = ttk.Entry(self.fields, textvariable=variable, width=width, show='*' if secret else '')
            entry.pack(side='left', padx=(0, 16))
            self.input_widgets.append(entry)

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.geometry(self.layout.get('settings_geometry', '860x800'))
        self.settings_window.bind('<Configure>', lambda e: self.schedule_save() if e.widget == self.settings_window else None, add='+')
        self.settings_window.minsize(760, 740)
        self.settings_window.protocol('WM_DELETE_WINDOW', self.close_settings)
        self.build_settings()

    def close_settings(self):
        self.save_settings()
        if self.settings_window: self.settings_window.destroy()
        self.settings_window = None
        self.mode_box = None
        self.input_widgets = []

    def build_settings(self):
        window = self.settings_window
        if window is None or not window.winfo_exists(): return
        for c in window.winfo_children(): c.destroy()
        window.title(self.t('settings') + ' · SCMaru ' + VERSION)
        window.configure(bg=self.palette['bg'])
        outer = ttk.Frame(window, padding=22)
        outer.pack(fill='both', expand=True)
        bottom = ttk.Frame(outer)
        bottom.pack(fill='x', side='bottom', pady=(10, 0))
        ttk.Label(bottom, textvariable=self.settings_notice, style='Muted.TLabel').pack(side='left')
        self.settings_notice.set(self.t('autosaved'))
        ttk.Button(bottom, text=self.t('close'), command=self.close_settings).pack(side='right')
        head = ttk.Frame(outer)
        head.pack(fill='x', pady=(0, 16))
        ttk.Label(head, text=self.t('settings'), style='Title.TLabel').pack(side='left')
        languages = ttk.Combobox(head, values=['System', '中文', '日本語'], state='readonly', width=10)
        languages.current({'system': 0, 'zh': 1, 'ja': 2}[self.lang_choice])
        languages.pack(side='right')
        languages.bind('<<ComboboxSelected>>', lambda e: self.change_language(('system', 'zh', 'ja')[languages.current()]))
        themes = ttk.Combobox(head, values=[self.t(k) for k in ('black', 'white', 'pink')], state='readonly', width=9)
        themes.current(('black', 'white', 'pink').index(self.theme))
        themes.pack(side='right', padx=10)
        themes.bind('<<ComboboxSelected>>', lambda e: self.change_theme(('black', 'white', 'pink')[themes.current()]))
        self.help(themes, 'theme_help')
        self.help(languages, 'language_help')
        tabs = ttk.Notebook(outer)
        tabs.pack(fill='both', expand=True)
        general, visual = ScrollPage(tabs,self.palette), ScrollPage(tabs,self.palette)
        tabs.add(general, text=self.t('general_tab'))
        tabs.add(visual, text=self.t('overlay_tab'))
        general,visual=general.content,visual.content
        layout_tab = ScrollPage(tabs,self.palette)
        tabs.add(layout_tab, text=self.t('layout_tab'))
        layout_tab=layout_tab.content
        font_row=ttk.Frame(layout_tab);font_row.pack(fill='x',pady=10)
        ttk.Label(font_row,text=self.t('ui_font'),width=24).pack(side='left')
        from fonts import FontDropdown
        selector=FontDropdown(font_row,self.ui_family,self.palette)
        selector.button.pack(side='left',fill='x',expand=True)
        scale_row=ttk.Frame(layout_tab);scale_row.pack(fill='x',pady=10)
        ttk.Label(scale_row,text=self.t('ui_scale'),width=24).pack(side='left')
        ttk.Spinbox(scale_row,from_=.75,to=1.6,increment=.05,format='%.2f',textvariable=self.ui_scale,state='readonly',width=8).pack(side='left')
        ttk.Label(layout_tab,text=self.t('ui_fallback'),style='Muted.TLabel').pack(anchor='w',pady=6)
        translation_tab = ScrollPage(tabs,self.palette)
        reminders_tab = ScrollPage(tabs,self.palette)
        tabs.add(translation_tab,text=self.t('translation_tab'))
        tabs.add(reminders_tab,text=self.t('reminders_tab'))
        translation_tab,reminders_tab=translation_tab.content,reminders_tab.content
        self.build_translation_settings(translation_tab)
        for key, low, high in [('sc_row_height', 40, 160), ('list_font_size', 8, 20), ('sc_detail_height', 1, 10), ('rank_detail_height', 1, 10)]:
            row = ttk.Frame(layout_tab)
            row.pack(fill='x', pady=14)
            ttk.Label(row, text=self.t(key), width=24).pack(side='left')
            ttk.Spinbox(row, from_=low, to=high, textvariable=self.layout_vars[key], width=7, state='readonly').pack(side='left')
        ttk.Label(layout_tab, text=self.t('layout_note'), wraplength=700, style='Muted.TLabel').pack(anchor='w', pady=12)
        advanced_tab = None
        if False:  # Legacy official-app credentials are retained locally, no longer requested in UI.
            advanced_tab = ttk.Frame(tabs, padding=14)
            tabs.add(advanced_tab, text=self.t('advanced_tab'))
        tabs.select(min(self.settings_tab, len(tabs.tabs())-1))
        tabs.bind('<<NotebookTabChanged>>', lambda e: self.change_settings_tab(tabs))
        self.mode_box = None
        ttk.Label(general, text=self.t('gift_login_note'), wraplength=710, style='Muted.TLabel').pack(anchor='w', pady=(6, 14))
        if self.mode.get() == 'room':
            login_row = ttk.Frame(general)
            login_row.pack(fill='x', pady=3)
            self.help(ttk.Label(login_row, text=self.t('login_saved' if self.session_cookie.get() else 'login_none')), 'login_help').pack(side='left')
            self.help(ttk.Button(login_row, text=self.t('qr_login'), command=self.open_qr_login), 'login_help').pack(side='left', padx=12)
            if self.session_cookie.get(): self.help(ttk.Button(login_row, text=self.t('logout'), command=self.logout), 'login_help').pack(side='left')
        options = ttk.Frame(general)
        options.pack(fill='x', pady=4)
        self.help(ttk.Checkbutton(options, text=self.t('auto_reset'), variable=self.auto_reset), 'auto_reset_help').pack(side='left', padx=16)
        reminders = ttk.LabelFrame(reminders_tab, text=self.t('reminder_settings'), padding=10)
        reminders.pack(fill='x', pady=12)
        for key in ('water', 'activity'):
            row = ttk.Frame(reminders)
            row.pack(fill='x', pady=3)
            enabled, interval = self.reminder_vars[key]
            self.help(ttk.Checkbutton(row, text=self.t(key + '_setting'), variable=enabled, width=20), 'reminder_help').pack(side='left')
            entry = ttk.Entry(row, textvariable=interval, width=9)
            entry.pack(side='left', padx=8)
            self.help(entry, 'interval_help')
            entry.bind('<FocusOut>', lambda e: self.normalize_reminders())
            entry.bind('<Return>', lambda e: self.normalize_reminders())
            ttk.Label(row, text=self.t('minutes_unit')).pack(side='left')
            ttk.Label(row, textvariable=self.reminder_countdowns[key], style='Muted.TLabel').pack(side='left', padx=12)
        ttk.Label(reminders, text=self.t('reminder_note'), wraplength=680, style='Muted.TLabel').pack(anchor='w', pady=5)
        sounds=ttk.LabelFrame(reminders_tab,text=self.t('sound_settings'),padding=12)
        sounds.pack(fill='x',pady=12)
        ttk.Checkbutton(sounds,text=self.t('sound_enabled'),variable=self.sound_enabled).pack(anchor='w')
        for key,var in [('new_sc_sound',self.sc_sound),('alarm_sound',self.alarm_sound)]:
            row=ttk.Frame(sounds);row.pack(fill='x',pady=5)
            ttk.Checkbutton(row,text=self.t(key),variable=var).pack(side='left')
            ttk.Button(row,text=self.t('sound_preview'),command=lambda k=key: self.play_sound('sc' if k=='new_sc_sound' else 'alarm',preview=True)).pack(side='right')
        ttk.Label(sounds,text=self.t('volume')).pack(anchor='w',pady=(8,0))
        ttk.Scale(sounds,from_=0,to=100,variable=self.sound_volume).pack(fill='x',pady=8)
        ttk.Label(general, text=self.t('scope_note'), wraplength=740, style='Muted.TLabel').pack(anchor='w', pady=20)
        ttk.Label(general,text=self.t('txt_autosave_note')+'\n'+str(self.ledger.export_directory),wraplength=710,style='Muted.TLabel').pack(anchor='w',pady=6)
        if getattr(sys, 'frozen', False) and not self.demo:
            ttk.Button(general, text=self.t('update'), command=self.check_update).pack(anchor='w', pady=4)
        self.help(ttk.Button(general, text=self.t('start_page'), command=self.open_start_page), 'start_help').pack(anchor='w', pady=8)
        from overlay_controls import build_controls
        build_controls(self, visual)
        if advanced_tab is not None: self.build_advanced(advanced_tab)
        self.render()
        self.apply_appearance()

    def open_start_page(self):
        if self.start_page and self.start_page.window.winfo_exists(): self.start_page.window.lift(); return
        from onboarding import StartPage
        self.start_page = StartPage(self)

    def open_qr_login(self, expired=False):
        if self.login_dialog and self.login_dialog.window.winfo_exists(): self.login_dialog.window.lift(); return
        from login import LoginDialog
        self.login_dialog = LoginDialog(self.root, self.t, self.palette, self.save_login, notice=self.t('login_expired') if expired else None)
        self.apply_appearance()

    def save_login(self, cookie):
        self.login_generation += 1
        self.login_expired = False
        self.session_cookie.set(cookie)
        self.save_settings()
        self.notice.set(self.t('qr_success'))
        self.build_settings()
        if self.start_page and self.start_page.window.winfo_exists(): self.start_page.login_completed()
        if self.collector.running and self.active_source == 'room':
            self.notice.set(self.t('login_reconnect'))
            self.reconnect()

    def logout(self):
        self.login_generation += 1
        self.login_expired = False
        self.session_cookie.set('')
        self.active_logged_in = False
        self._protected_cache.pop('session', None)
        self.save_settings()
        self.build_settings()
        if self.collector.running and self.active_source == 'room': self.reconnect()

    def reconnect(self):
        self.disconnect()
        def resume():
            if self.closing: return
            if self.collector.running: self.root.after(300, resume)
            else: self.connect()
        self.root.after(500, resume)

    def open_overlay_preview(self):
        if not self.overlay: return
        import webbrowser
        webbrowser.open(self.overlay.url('preview'))

    def build_advanced(self, outer):
        advanced = ttk.LabelFrame(outer, text=self.t('advanced'), padding=10)
        advanced.pack(fill='x', pady=16)
        ttk.Label(advanced, text=self.t('advanced_note'), style='Muted.TLabel', wraplength=780).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        for index, (key, variable, secret) in enumerate([('App ID', self.app_id, False), ('Access Key ID', self.access_key_id, True), ('Access Key Secret', self.access_key_secret, True)], 1):
            ttk.Label(advanced, text=key).grid(row=index, column=0, sticky='w', padx=(0, 12), pady=3)
            entry = ttk.Entry(advanced, textvariable=variable, show='*' if secret else '')
            entry.grid(row=index, column=1, sticky='ew', pady=3)
            self.input_widgets.append(entry)
        advanced.columnconfigure(1, weight=1)

    def show_auth_guide(self):
        from guide import show_guide
        show_guide(self.root, self.lang, self.palette)

    def change_language(self, choice):
        self.lang_choice = choice
        self.lang = language(choice, system_language())
        self.save_settings()
        self.build()
        self.render()
        self.build_settings()

    def change_theme(self, value):
        if value not in PALETTES: return
        self.theme = value
        self.save_settings()
        self.style()
        self.build()
        self.render()
        self.build_settings()

    def change_mode(self, e=None):
        self.mode.set(('room', 'livehime')[self.mode_box.current()])
        self.build_settings()
        self.save_settings()

    def change_settings_tab(self, tabs):
        if not tabs.winfo_exists() or not tabs.select(): return
        selected = tabs.index(tabs.select())
        if selected != self.settings_tab:
            self.settings_tab = selected
            self.schedule_save()

    def save_settings(self):
        if self.save_timer:
            self.root.after_cancel(self.save_timer)
            self.save_timer = None
        def encrypted(key, value):
            if not value: return ''
            cached = self._protected_cache.get(key)
            if cached and cached[0] == value: return cached[1]
            protected = protect(value)
            self._protected_cache[key] = (value, protected)
            return protected
        self.capture_layout()
        self.ledger.save_settings(dict(language=self.lang_choice, mode=self.mode.get(), room=self.room.get(),
            auto_reset=self.auto_reset.get(), video=self.video.get(), show_start_page=self.show_start_page.get(),
            settings_tab=self.settings_tab, template=self.template.get(), overlay_font=self.overlay_font.get(),
            overlay_size=self.overlay_size.get(), overlay_color=self.overlay_color,
            theme=self.theme, filter=self.filter.get(), user_search=self.user_search.get(), rank_scope=self.rank_scope.get(), app_id=self.app_id.get(),
            remember_auth=self.remember_auth.get(), auth_protected=encrypted('auth', self.auth.get()) if self.remember_auth.get() else '',
            access_key_id_protected=encrypted('key_id', self.access_key_id.get()),
            access_key_secret_protected=encrypted('key_secret', self.access_key_secret.get()),
            session_cookie_protected=encrypted('session', self.session_cookie.get()),
            login_expired=self.login_expired,
            appearance=dict(font=self.ui_family.get(),scale=self.ui_scale.get()),
            sound=dict(enabled=self.sound_enabled.get(),sc=self.sc_sound.get(),alarm=self.alarm_sound.get(),volume=self.sound_volume.get()),
            translation=dict(enabled=self.translation_enabled.get(),auto_new=self.auto_translate_new.get(),hide_original=self.hide_original.get(),list_enabled=self.list_translation_enabled.get(),zh_to_ja=self.zh_to_ja.get(),ja_to_zh=self.ja_to_zh.get(),mode=self.translation_mode.get(),url=self.translation_url.get(),model=self.translation_model.get(),key_protected=encrypted('translation_key',self.translation_key.get())),
            overlay_effects={key: variable.get() for key, variable in self.overlay_effects.items()},
            layout=self.layout,
            reminders={key: dict(enabled=pair[0].get(), minutes=minutes(pair[1].get(), 10 if key == 'water' else 60)) for key, pair in self.reminder_vars.items()}))
        self.settings_notice.set(self.t('saved_notice'))

    def capture_layout(self):
        for window, key in [(self.settings_window, 'settings_geometry'),
                            (self.start_page.window if self.start_page else None, 'start_geometry')]:
            if window is not None and window.winfo_exists() and window.winfo_viewable():
                self.layout[key] = window.geometry()
        if not self.main_frame or not self.root.winfo_viewable(): return
        if self.root.state() != 'zoomed': self.layout['geometry'] = self.root.geometry()
        self.layout['maximized'] = self.root.state() == 'zoomed'
        if hasattr(self, 'panes') and self.panes.winfo_exists() and self.panes.winfo_width() > 200:
            self.layout['split'] = self.panes.sashpos(0) / self.panes.winfo_width()
        if hasattr(self, 'sc_tree') and self.sc_tree.winfo_exists():
            self.layout['sc_columns'] = dict(zip(('#0', 'time', 'user', 'amount'), self.sc_tree.widths))
            self.layout['sc_row_height'] = self.sc_tree.row_height
        if hasattr(self, 'rank_tree') and self.rank_tree.winfo_exists():
            self.layout['rank_columns'] = {key: self.rank_tree.column(key)['width'] for key in ('user', 'amount')}
        if hasattr(self, 'detail') and self.detail.winfo_exists():
            self.layout['sc_detail_height'] = int(self.detail.cget('height'))
            self.layout['rank_detail_height'] = int(self.rank_detail.cget('height'))
        if hasattr(self,'detail_split') and self.detail_split.winfo_exists() and self.detail_split.winfo_height()>180:
            self.layout['sc_detail_pixels']=self.detail_split.winfo_height()-self.detail_split.sashpos(0)

    def change_layout_sizes(self, *args):
        for key, variable in self.layout_vars.items(): self.layout[key] = variable.get()
        self.sc_tree.row_height = self.layout_vars['sc_row_height'].get()
        self.sc_tree.font_size = self.layout_vars['list_font_size'].get()
        self.style()
        self.confirm_blue_btn.configure(image=self.blue_confirm_icon)
        self.detail.configure(height=self.layout_vars['sc_detail_height'].get())
        if self.detail_split.winfo_height()>180:
            pixels=60+self.layout_vars['sc_detail_height'].get()*(self.layout_vars['list_font_size'].get()+10)
            self.detail_split.sashpos(0,max(80,self.detail_split.winfo_height()-pixels))
        self.rank_detail.configure(height=self.layout_vars['rank_detail_height'].get())
        self.render_dirty = True
        self.render()
        self.schedule_save()

    def normalize_reminders(self):
        for key, (_, variable) in self.reminder_vars.items():
            variable.set(str(minutes(variable.get(), 10 if key == 'water' else 60)))

    def help(self, widget, key):
        widget.help_bubble = Tooltip(widget, self.t(key), self.palette)
        return widget

    def change_video_mode(self, *args):
        if self.video.get():
            self.export_dirty |= bool(self.ledger.classify_video_sc())
            if not self.confirm_blue_btn.winfo_manager(): self.confirm_blue_btn.pack(side='left', padx=6)
        else: self.confirm_blue_btn.pack_forget()
        self.render_dirty = True
        self.render()
        self.schedule_save()

    def confirm_blue(self):
        if not self.video.get(): return
        count = self.ledger.confirm_squares()
        self.export_dirty |= bool(count)
        self.notice.set(self.t('blue_confirmed', count=count))
        self.render_dirty = True
        self.render()

    def reminder_changed(self, *args):
        self.update_reminders()
        self.schedule_save()

    def dismiss_reminder(self, key):
        self.reminders.reset(key)
        self.update_reminders()

    def update_reminders(self):
        settings = {key: (pair[0].get(), minutes(pair[1].get(), 10 if key == 'water' else 60)) for key, pair in self.reminder_vars.items()}
        due = self.reminders.advance(time.monotonic(), self.status == 'connected', settings)
        if set(due)-self.reminder_due and not self.demo: self.play_sound('alarm')
        self.reminder_due=set(due)
        for key, button in self.reminder_buttons.items():
            interval = settings[key][1]
            seconds = self.reminders.remaining(key, interval)
            formatted = f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'
            label = self.t('reminder_disabled') if not settings[key][0] else self.t('countdown_left', time=formatted)
            if settings[key][0] and self.status != 'connected': label += ' · ' + self.t('countdown_paused')
            self.reminder_countdowns[key].set(label)
            if key in due:
                if not button.winfo_manager(): button.pack(side='left', padx=8)
                button.set_active(True)
            else:
                button.set_active(False)
                button.pack_forget()

    def play_sound(self, kind, preview=False):
        enabled=self.sc_sound.get() if kind=='sc' else self.alarm_sound.get()
        if preview or (self.sound_enabled.get() and enabled): self.sound_player.play(kind,self.sound_volume.get())

    def apply_appearance(self):
        apply_widgets(self.root,resolve_family(self.root,self.ui_family.get()),self.ui_scale.get())

    def change_appearance(self,*args):
        if self.appearance_timer: self.root.after_cancel(self.appearance_timer)
        def update():
            self.appearance_timer=None
            self.style()
            self.render()
            self.apply_appearance()
            self.summary.configure(height=round(46*self.ui_scale.get()))
            self.root.minsize(round(940*self.ui_scale.get()),round(600*self.ui_scale.get()))
            self.schedule_save()
        self.appearance_timer=self.root.after(350,update)

    def schedule_save(self, *args):
        if self.closing: return
        if self.save_timer: self.root.after_cancel(self.save_timer)
        self.save_timer = self.root.after(500, self.auto_save)
        self.update_overlay()

    def auto_save(self):
        self.save_timer = None
        try: self.save_settings()
        except OSError: self.settings_notice.set(self.t('error'))

    def change_grouping(self):
        self.ledger.sink_processed()
        self.render_dirty = True
        self.render()

    def choose_color(self):
        color = colorchooser.askcolor(color=self.overlay_color, parent=self.root)[1]
        if color:
            self.overlay_color = color
            self.save_settings()
            self.update_overlay()

    def connect(self):
        if self.demo or self.collector.running or self.update_busy: return
        if self.mode.get() == 'livehime':
            self.notice.set(self.t('livehime_note'))
            self.open_settings()
            return
        if (self.mode.get() == 'room' and not self.room.get().strip()) or (self.mode.get() == 'open' and not self.auth.get().strip()):
            self.main_room_entry.focus_set()
            self.notice.set(self.t('setup_room_required'))
            return
        try:
            self.collector.start(self.mode.get(), self.room.get().strip(), self.auth.get().strip(),
                                 self.access_key_id.get().strip(), self.access_key_secret.get().strip(), self.app_id.get().strip(),
                                 session_cookie=self.session_cookie.get())
        except (ValueError, RuntimeError) as e:
            messagebox.showerror(self.t('error'), str(e), parent=self.root)
            return
        self.status, self.status_extra = 'connecting', ''
        self.offline_deadline = None
        self.seen_live = False
        self.heartbeat = 0
        self.reminders = Reminders()
        self.save_settings()
        self.render_dirty = True

    def disconnect(self):
        self.offline_deadline = None
        self.collector.stop()
        self.status = 'disconnected'
        self.update_reminders()
        self.render_dirty = True

    def set_filter(self, value):
        self.filter.set(value)
        self.render_dirty = True

    def change_user_search(self,*args):
        self.render_dirty=True
        self.schedule_save()

    def set_scope(self, value):
        self.rank_scope.set(value)
        self.render_dirty = True

    def set_mark(self, mark, *, refresh=False):
        for event_id in self.sc_tree.selection():
            row = self.ledger.db.execute('SELECT mark FROM events WHERE id=? AND session=?', (event_id, self.ledger.session)).fetchone()
            if row:
                self.ledger.mark(event_id, '' if row['mark'] == mark else mark)
        self.export_dirty = True
        if refresh:
            self.update_overlay(pending=self.render_sc(allow_request=True))
        else:
            self.render_dirty = True

    def click_mark(self, event, mark):
        if not hasattr(event, 'item_id') and self.sc_tree.identify_region(event.x, event.y) not in ('tree', 'cell'):
            return None
        item = event.item_id if hasattr(event, 'item_id') else self.sc_tree.identify_row(event.y)
        if item == '__processed_separator__':
            return 'break'
        if item:
            self.sc_tree.selection_set(item, notify=False)
            column = event.column_id if hasattr(event, 'column_id') else self.sc_tree.identify_column(event.x)
            if column == '#0':
                self.set_mark(mark, refresh=True)
            else:
                self.select_sc()
                if mark == 'circle':
                    self.copy_sc_bv(item)
            return 'break'

    def copy_sc_bv(self, item):
        row = self.ledger.db.execute('SELECT text,deleted FROM events WHERE id=?', (item,)).fetchone()
        if not row or row['deleted']: return
        ids = list(dict.fromkeys(BV.findall(row['text'])))
        if ids:
            self.root.clipboard_clear()
            self.root.clipboard_append('\n'.join(ids))
            self.notice.set(self.t('bv_copied', bv='、'.join(ids)))

    @staticmethod
    def fill_text(widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        widget.configure(state='disabled')

    def select_sc(self, e=None, *, allow_request=True):
        selected = self.sc_tree.selection()
        if selected:
            r = self.ledger.db.execute('SELECT * FROM events WHERE id=?', (selected[0],)).fetchone()
            if r:
                text = self.t('removed') if r['deleted'] else r['text']
                self.fill_text(self.detail, f"{r['name']} · {batteries(r['amount'])} {self.t('amount')}\n{text}")
                self.translate_selected(r,text,allow_request=allow_request)

    def translation_config(self):
        return dict(mode=self.translation_mode.get(),url=self.translation_url.get().strip(),model=self.translation_model.get().strip(),key=self.translation_key.get().strip(),zh_to_ja=self.zh_to_ja.get(),ja_to_zh=self.ja_to_zh.get())

    def build_translation_settings(self, parent):
        ttk.Label(parent,text=self.t('translation_help'),wraplength=710).pack(anchor='w',pady=10)
        directions=ttk.Frame(parent);directions.pack(fill='x',pady=8)
        ttk.Checkbutton(directions,text=self.t('zh_to_ja'),variable=self.zh_to_ja).pack(side='left')
        ttk.Checkbutton(directions,text=self.t('ja_to_zh'),variable=self.ja_to_zh).pack(side='left',padx=18)
        row=ttk.Frame(parent);row.pack(fill='x',pady=10)
        ttk.Label(row,text=self.t('translation_engine'),width=18).pack(side='left')
        engines=('api_first','api_only','google_only')
        combo=ttk.Combobox(row,values=[self.t(k) for k in engines],state='readonly',width=28)
        combo.current(engines.index(self.translation_mode.get()))
        combo.pack(side='left')
        combo.bind('<<ComboboxSelected>>',lambda e:self.translation_mode.set(engines[combo.current()]))
        for key,var,secret in [('api_url',self.translation_url,False),('api_model',self.translation_model,False),('api_key',self.translation_key,True)]:
            row=ttk.Frame(parent);row.pack(fill='x',pady=10)
            ttk.Label(row,text=self.t(key),width=18).pack(side='left')
            ttk.Entry(row,textvariable=var,show='*' if secret else '').pack(side='left',fill='x',expand=True)
        presets=ttk.Frame(parent);presets.pack(fill='x',pady=10)
        ttk.Button(presets,text='DeepSeek',command=lambda:self.translation_preset('https://api.deepseek.com','deepseek-flash')).pack(side='left')
        ttk.Button(presets,text='OpenAI',command=lambda:self.translation_preset('https://api.openai.com/v1','')).pack(side='left',padx=10)
        ttk.Label(parent,text=self.t('translation_settings_note'),wraplength=710,style='Muted.TLabel').pack(anchor='w',pady=14)

    def translation_preset(self,url,model):
        self.translation_url.set(url)
        self.translation_model.set(model)

    def change_translation(self,*args):
        self.translation_token+=1
        if self.translation_worker: self.translation_worker.stop()
        self.translation_worker=None
        self.translation_current=None
        self.translation_pending.clear()
        self.render_dirty=True
        if self.translation_timer: self.root.after_cancel(self.translation_timer)
        def resume():
            self.translation_timer=None
            self.select_sc()
            self.start_next_translation()
        self.translation_timer=self.root.after(500,resume)
        self.sync_hide_original()
        self.select_sc()
        self.schedule_save()

    def change_list_translation(self,*args):
        self.render_dirty=True
        self.schedule_save()

    def sync_hide_original(self):
        enabled=self.translation_enabled.get()
        self.hide_original_btn.state(['!disabled' if enabled else 'disabled',
                                      'selected' if enabled and self.hide_original.get() else '!selected'])

    def change_hide_original(self,*args):
        self.sync_hide_original()
        self.select_sc()
        self.schedule_save()

    def retry_translation(self):
        selected=self.sc_tree.selection()
        if selected:
            row=self.ledger.db.execute('SELECT * FROM events WHERE id=?',(selected[0],)).fetchone()
            if row: self.translation_cache.pop((row['id'],row['text'],fingerprint(self.translation_config())),None)
        self.render_dirty=True
        self.select_sc()

    def append_translation(self,result,hide_original=False):
        self.detail.configure(state='normal')
        if result.get('error'):
            self.detail.insert('end','\n\n'+self.t(result['error']),'translation_meta')
        else:
            if hide_original:
                self.detail.delete('2.0','end')
            heading='日本語' if result.get('target')=='ja' else '中文'
            spacing='\n' if hide_original else '\n\n'
            self.detail.insert('end',f"{spacing}{heading} · {result.get('engine','')}\n",'translation_meta')
            self.detail.insert('end',result['text'],'translation')
        self.detail.configure(state='disabled')

    def translate_selected(self,row,text,*,allow_request=True):
        if not self.translation_enabled.get() or row['deleted']: return
        if self.translation_timer: return
        config=self.translation_config()
        key=(row['id'],text,fingerprint(config))
        if key in self.translation_cache:
            result=self.translation_cache[key]
            translated=result.get('text')
            if result.get('error'):
                self.append_translation(result)
            elif isinstance(translated,str) and translated.strip() and translated.strip()!=text.strip() and not result.get('skipped'):
                self.append_translation(result,hide_original=self.hide_original.get())
            return
        if allow_request:
            self.queue_translation(key, priority=True)
        if key == self.translation_current or key in self.translation_pending:
            self.append_translation(dict(error='translation_loading'))

    def queue_translation(self, key, *, priority=False):
        if key == self.translation_current or key in self.translation_cache or self.closing:
            return
        self.translation_pending[key] = None
        if priority:
            self.translation_pending.move_to_end(key, last=False)
        self.start_next_translation()

    def start_next_translation(self):
        if self.translation_worker or self.translation_timer or self.closing:
            return
        config = self.translation_config()
        while self.translation_pending:
            key, _ = self.translation_pending.popitem(last=False)
            event_id, text, settings = key
            if key in self.translation_cache or settings != fingerprint(config):
                continue
            if not self.ledger.db.execute(
                "SELECT 1 FROM events WHERE id=? AND session=? AND deleted=0 AND batch=''",
                (event_id, self.ledger.session),
            ).fetchone():
                continue
            self.translation_token += 1
            self.translation_current = key
            self.translation_worker = TranslationWorker(self.queue)
            self.translation_worker.start(self.translation_token, text, config)
            return

    def list_translation(self,row):
        if not self.list_translation_enabled.get() or row['deleted']: return ''
        key=(row['id'],row['text'],fingerprint(self.translation_config()))
        result=self.translation_cache.get(key,{})
        value=result.get('text','')
        if result.get('skipped') or result.get('error') or not isinstance(value,str):
            return ''
        return value if value.strip() and value.strip()!=row['text'].strip() else ''

    def select_rank(self, e=None):
        selected = self.rank_tree.selection()
        if not selected: return
        user = selected[0]
        rows = self.ledger.db.execute('SELECT * FROM events WHERE room=? AND source=? AND user=? ORDER BY ts DESC',
                                      (self.active_room, self.active_source, user)).fetchall()
        if self.rank_scope.get() == 'session':
            rows = [r for r in rows if r['session'] == self.ledger.session]
        else:
            day = datetime.now().date()
            rows = [r for r in rows if datetime.fromtimestamp(r['ts']).date() == day]
        def kind_name(kind):
            return 'SC' if kind == 'sc' else self.t(kind + '_kind')
        def content(row):
            text = row['text']
            if row['kind'] == 'guard':
                for num, name in [(1, '总督' if self.lang == 'zh' else '総督'), (2, '提督'), (3, '舰长' if self.lang == 'zh' else '艦長')]:
                    text = text.replace(f'Guard {num}', name)
            return text
        self.fill_text(self.rank_detail, '\n'.join(f"{datetime.fromtimestamp(r['ts']):%H:%M:%S} · {kind_name(r['kind'])} · {batteries(r['amount'])} {self.t('amount')} · {content(r)}" for r in rows))

    def reset(self):
        if not self.ledger.session: return
        if messagebox.askyesno(self.t('reset'), self.t('reset_ask', n=len(self.ledger.sc_rows())), parent=self.root, default='no'):
            try:
                self.ledger.export()  # A failed export must not clear the visible list.
                self.ledger.archive()
                self.ledger.export()
                self.render_dirty = True
            except OSError as e:
                messagebox.showerror(self.t('error'), str(e), parent=self.root)

    def export_now(self):
        try:
            path = self.ledger.export()
            if path: self.notice.set(self.t('saved') + str(path))
        except OSError as e:
            messagebox.showerror(self.t('error'), str(e), parent=self.root)

    def open_exports(self):
        try:
            path=self.ledger.export_directory.resolve()
            path.mkdir(parents=True,exist_ok=True)
            os.startfile(str(path))
            self.notice.set(self.t('txt_directory')+str(path))
        except OSError as exc:
            messagebox.showerror(self.t('error'),str(exc),parent=self.root)

    def check_update(self):
        if self.update_busy:
            return
        if self.collector.running:
            messagebox.showinfo(self.t('update'), self.t('update_disconnect'), parent=self.root)
            return
        self.run_update_task(lambda: updater.check(VERSION), self.offer_update)

    def run_update_task(self, action, on_success):
        self.update_busy = True
        self.notice.set(self.t('update_working'))
        result = queue.Queue()

        def work():
            try:
                result.put((True, action()))
            except Exception as error:
                result.put((False, type(error).__name__))

        def poll():
            try:
                success, value = result.get_nowait()
            except queue.Empty:
                self.root.after(200, poll)
                return
            self.update_busy = False
            self.notice.set('')
            if success:
                on_success(value)
            else:
                messagebox.showerror(self.t('update'), self.t('update_failed', error=value), parent=self.root)

        Thread(target=work, daemon=True).start()
        self.root.after(200, poll)

    def offer_update(self, release):
        if release is None:
            messagebox.showinfo(self.t('update'), self.t('update_latest'), parent=self.root)
            return
        if messagebox.askyesno(self.t('update'), self.t('update_ask', version=release[0]), parent=self.root):
            install_dir = Path(sys.executable).resolve().parent
            self.run_update_task(lambda: updater.stage_update(release, install_dir), self.finish_update)

    def finish_update(self, staging):
        self.update_stage = staging
        self.close()

    def scan_txt_archives(self, *, force=False):
        folder = self.ledger.export_directory
        files = {}
        for path in sorted(folder.glob('*.txt')):
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                cached = self.txt_seen.get(path)
                if not force and cached and cached[0] == signature:
                    files[path] = cached
                else:
                    files[path] = signature, import_file(self.ledger, path)
            except (OSError, ValueError, OverflowError):
                continue
        self.txt_seen = files
        return {session_id for _, session_id in files.values() if session_id}

    def history(self):
        window = tk.Toplevel(self.root)
        window.title(self.t('history'))
        window.geometry('820x480')
        window.configure(bg=self.palette['bg'])
        box = tk.Listbox(window, bg=self.palette['input'], fg=self.palette['fg'], font=('Segoe UI', 11), selectbackground=self.palette['accent'], selectforeground=self.palette['fg'])
        box.pack(fill='both', expand=True, padx=12, pady=12)
        entries = []

        def refresh(*, force=False):
            available = self.scan_txt_archives(force=force)
            updated = []
            for row in self.ledger.db.execute('SELECT * FROM sessions ORDER BY started DESC'):
                if row['id'] not in available:
                    continue
                label = f"{datetime.fromtimestamp(row['started']):%Y-%m-%d %H:%M:%S}  Room {row['room']}  {row['source']}"
                updated.append(('session', row['id'], row['id'], label))
                for a in self.ledger.db.execute('SELECT * FROM archives WHERE session=? AND restored=0 ORDER BY created DESC', (row['id'],)):
                    label = f"    ↳ {datetime.fromtimestamp(a['created']):%H:%M:%S}  {a['reason']}"
                    updated.append(('archive', a['id'], row['id'], label))
            if updated == entries:
                return
            selected = entries[box.curselection()[0]] if box.curselection() else None
            entries[:] = updated
            box.delete(0, 'end')
            box.insert('end', *(entry[3] for entry in entries))
            if selected in entries:
                index = entries.index(selected)
                box.selection_set(index)
                box.see(index)

        def poll_history():
            if not self.closing and window.winfo_exists():
                refresh()
                self.root.after(2000, poll_history)

        poll_history()
        ttk.Label(window, text=self.t('txt_history_refresh'), wraplength=780, style='Muted.TLabel').pack(padx=12)
        ttk.Label(window, text=self.t('history_note'), wraplength=780).pack(padx=12, pady=6)

        def act():
            refresh()
            if not box.curselection(): return
            kind, item_id, sid, _ = entries[box.curselection()[0]]
            if self.collector.running and sid != self.ledger.session:
                messagebox.showinfo(self.t('history'), self.t('history_note'), parent=window)
                return
            row = self.ledger.db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
            self.ledger.session = sid
            self.active_room, self.active_source = row['room'], row['source']
            self.ended = bool(row['ended'])
            if kind == 'archive': self.ledger.restore(item_id)
            self.export_dirty = True
            self.render_dirty = True
            window.destroy()

        actions = ttk.Frame(window)
        actions.pack(pady=10)
        ttk.Button(actions, text=self.t('refresh_history'), command=lambda: refresh(force=True)).pack(side='left', padx=5)
        ttk.Button(actions, text=self.t('view') + ' / ' + self.t('restore'), command=act).pack(side='left', padx=5)

    def copy_overlay(self):
        if not self.overlay:
            messagebox.showerror(self.t('error'), self.overlay_error, parent=self.root)
            return
        url = self.overlay.url()
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.notice.set(self.t('copied') + url)

    def update_overlay(self, *, pending=None, total=None):
        if not self.overlay: return
        if total is None:
            total = sum(r['total'] for r in self.ledger.rankings(self.active_room, self.active_source, daily=False))
        if pending is None:
            pending = self.ledger.pending()
        text = self.template.get()
        for key, value in {'pending': pending, 'total': batteries(total), 'date': datetime.now().strftime('%Y-%m-%d')}.items():
            text = text.replace('{' + key + '}', str(value))
        try: size = max(10, min(240, round(float(self.overlay_size.get()))))
        except ValueError: size = 36
        self.overlay.update(text, self.status == 'connected', self.t('disconnected'), size=size,
                            color=self.overlay_color, font=self.overlay_font.get(),
                            **{key: variable.get() for key, variable in self.overlay_effects.items()})

    def change_sc_sort(self, column):
        self.sc_sort_reverse = not self.sc_sort_reverse if column == self.sc_sort else column == 'amount'
        self.sc_sort = column
        self.render()

    def change_rank_sort(self):
        self.rank_sort = 'time' if self.rank_sort == 'amount' else 'amount'
        self.render()

    def render(self):
        running = self.collector.running
        self.connect_btn.configure(state='disabled' if running or self.demo else 'normal')
        self.disconnect_btn.configure(state='normal' if running else 'disabled')
        self.main_room_entry.configure(state='disabled' if running else 'normal')
        if self.mode_box is not None and self.mode_box.winfo_exists():
            self.mode_box.configure(state='disabled' if running else 'readonly')
        for w in self.input_widgets:
            if w.winfo_exists(): w.configure(state='disabled' if running else 'normal')
        source = self.active_source if self.status == 'connected' else self.mode.get()
        mode_text = self.t(('status_mode_room_login' if self.active_logged_in else 'status_mode_room') if source == 'room' else 'livehime_mode' if source == 'livehime' else 'status_mode_open')
        status_text = self.t(self.status)
        if self.status == 'connected': status_text += ' · ' + (self.active_anchor or self.t('anchor_unavailable'))
        self.status_label.configure(text=status_text + ' · ' + mode_text + self.status_extra)
        pending = self.render_sc()
        daily = self.rank_scope.get() == 'day'
        rankings = self.ledger.rankings(self.active_room, self.active_source, daily=daily)
        if self.rank_sort == 'time':
            rankings.sort(key=lambda row: (row['latest_gift'] is None, -(row['latest_gift'] or 0)))
        self.rank_sort_label.configure(text=self.t('rank_sort_' + self.rank_sort))
        total = sum(r['total'] for r in rankings)
        current = self.ledger.current()
        date = datetime.now().strftime('%Y-%m-%d') if daily or not current else datetime.fromtimestamp(current['started']).strftime('%Y-%m-%d %H:%M')
        gross_key = 'gross' if daily else ('session_gross' if current and current['start_known'] else 'capture_gross')
        self.total_label.configure(text=self.t(gross_key, date=date, amount=batteries(total)))
        rank_signature = (self.active_room, self.active_source, self.ledger.session, daily, date,
                          tuple(tuple(r) for r in rankings))
        if self.rank_signature != rank_signature:
            rank_selected = self.rank_tree.selection()
            rank_scroll = self.rank_tree.yview()
            self.rank_tree.delete(*self.rank_tree.get_children())
            for index, r in enumerate(rankings, 1):
                self.rank_tree.insert('', 'end', iid=r['user'], values=(f"{index}. {r['name']}", batteries(r['total'])))
            if rank_selected and self.rank_tree.exists(rank_selected[0]):
                self.rank_tree.selection_set(rank_selected)
                self.select_rank()
            else: self.fill_text(self.rank_detail, '')
            if rank_scroll: self.rank_tree.yview_moveto(rank_scroll[0])
            self.rank_signature = rank_signature
        self.update_overlay(pending=pending, total=None if daily else total)
        self.render_dirty = False

    def render_sc(self, *, allow_request=False):
        rows = self.ledger.sc_rows()
        pending = sum(r['mark'] != 'circle' and not r['deleted'] for r in rows)
        self.count_label.configure(text=self.t('count', n=pending))
        direction = 'desc' if self.sc_sort_reverse else 'asc'
        self.sc_sort_label.configure(text=self.t('sc_sort_' + self.sc_sort + '_' + direction))
        selected = set(self.sc_tree.selection())
        scroll = self.sc_tree.yview()
        filt = self.filter.get()
        rows = [r for r in rows if filt == 'all' or (filt == 'pending' and r['mark'] != 'circle' and not r['deleted']) or r['mark'] == filt]
        rows = [r for r in rows if matches_user(r['name'],self.user_search.get())]
        entries = []
        def sort_key(row):
            primary = variants(row['name'])[1] if self.sc_sort == 'user' else row[self.sc_sort if self.sc_sort != 'time' else 'ts']
            return primary, row['ts'], row['id']

        for r in grouped_sc(rows, True, key=sort_key, reverse=self.sc_sort_reverse):
            if r is None:
                entries.append(('__processed_separator__', self.t('processed_divider'), '',
                                ('', '', '', '────────────────────────'), ('divider',), ''))
                continue
            label = self.t(r['mark']) if r['mark'] else ''
            content = self.t('removed') if r['deleted'] else r['text']
            values = (datetime.fromtimestamp(r['ts']).strftime('%m-%d %H:%M:%S'), r['name'], batteries(r['amount']), content)
            tags = (('removed',) if r['deleted'] else ()) + (('square',) if r['mark'] == 'square' else ())
            entries.append((r['id'], label, self.icons.get(r['mark'], ''), values, tags, self.list_translation(r)))
        new_frames = self.sc_tree.sync(entries)
        if new_frames:
            family = resolve_family(self.root, self.ui_family.get())
            scale = self.ui_scale.get()
            for frame in new_frames:
                apply_widgets(frame, family, scale)
        valid = selected.intersection(r['id'] for r in rows)
        if valid:
            self.sc_tree.selection_set(*valid, notify=False)
            self.select_sc(allow_request=allow_request)
        else: self.fill_text(self.detail, '')
        if scroll: self.sc_tree.yview_moveto(scroll[0])
        return pending

    def handle(self, kind, data):
        if self.closing and kind in ('translation','login_checked'): return
        if kind=='translation':
            if data['token']!=self.translation_token: return
            if self.translation_current:
                self.translation_cache[self.translation_current]=data['result']
                if len(self.translation_cache)>128: self.translation_cache.pop(next(iter(self.translation_cache)))
                self.render_dirty=True
            self.translation_current = None
            self.translation_worker = None
            self.start_next_translation()
            self.select_sc(allow_request=False)
            return
        if kind == 'login_checked':
            if data['generation'] != self.login_generation: return
            if data['valid'] is False:
                self.login_expired = True
                self.session_cookie.set('')
                self.active_logged_in = False
                self.save_settings()
                self.prompt_expired_login()
            elif data['valid'] is None: self.notice.set(self.t('login_check_unknown'))
            return
        if kind == 'room':
            self.active_room, self.active_source = data['room'], data['source']
            scope = (self.active_room, self.active_source)
            name = data.get('anchor_name', '')
            if name: self.anchor_names[scope] = name
            self.active_anchor = self.anchor_names.get(scope, '')
            self.active_logged_in = bool(data.get('logged_in'))
            info = data.get('info')
            stamp = info.get('timestamp') if info and info['live'] else None
            self.ledger.attach(self.active_room, self.active_source, stamp, fresh=info is None)
            self.seen_live = bool(info and info['live'])
            if info is None: self.notice.set(self.t('start_unknown'))
            self.ended = False
        elif kind == 'event':
            # Late messages after an end still belong to the previous capture;
            # only a verified live/start signal establishes the next broadcast.
            added=self.ledger.ingest(data, self.video.get())
            self.export_dirty |= added
            if added and data['kind']=='sc' and not self.demo:
                self.play_sound('sc')
                if self.auto_translate_new.get():
                    key = (data['id'], data['text'], fingerprint(self.translation_config()))
                    self.queue_translation(key)
        elif kind == 'delete':
            self.ledger.delete_sc(**data)
            self.export_dirty = True
        elif kind == 'heartbeat':
            self.heartbeat = time.monotonic()
            self.status = 'connected'
        elif kind in ('live', 'room_state'):
            if data.get('anchor_name'):
                self.active_anchor = data['anchor_name']
                self.anchor_names[(self.active_room, self.active_source)] = self.active_anchor
            if data['live']:
                self.seen_live = True
                self.offline_deadline = None
                self.ledger.attach(self.active_room, self.active_source, data.get('timestamp'))
                self.ended = False
                self.export_dirty = True
            elif self.seen_live and not self.ended and self.offline_deadline is None:
                self.offline_deadline = time.monotonic() + 90
                if self.auto_reset.get(): self.notice.set(self.t('ending'))
        elif kind in ('stopped', 'reconnecting', 'error'):
            self.offline_deadline = None
            self.status = 'reconnecting' if kind == 'reconnecting' else 'disconnected'
            if kind == 'error': self.notice.set(self.t('error') + ': ' + data)
        elif kind == 'warning':
            if data == 'room_state': self.offline_deadline = None
            self.notice.set(self.t(data))
        self.render_dirty = True

    def tick(self):
        if self.closing: return
        try:
            for _ in range(500):
                try: kind, data = self.queue.get_nowait()
                except queue.Empty: break
                self.handle(kind, data)
            if self.status == 'connected' and self.heartbeat and time.monotonic() - self.heartbeat > 75:
                self.status = 'reconnecting'
                self.offline_deadline = None
                self.render_dirty = True
            if self.offline_deadline and time.monotonic() >= self.offline_deadline:
                self.ledger.export()
                if self.auto_reset.get(): self.ledger.archive('offline', end=True)
                else: self.ledger.end()
                self.ledger.export()
                self.ended = True
                self.seen_live = False
                self.offline_deadline = None
                self.notice.set(self.t('archived' if self.auto_reset.get() else 'ended'))
                self.render_dirty = True
            if self.export_dirty:
                self.ledger.export()
                self.export_dirty = False
            self.update_reminders()
            # Also refresh the day boundary and source status without a new event.
            if self.render_dirty or getattr(self, 'last_day', None) != datetime.now().date():
                self.render()
                self.last_day = datetime.now().date()
        except (OSError, ValueError) as e:
            self.offline_deadline = None
            self.notice.set(self.t('error') + ': ' + type(e).__name__)
        self.root.after(500, self.tick)

    def load_demo(self):
        self.active_room, self.active_source = 'DEMO', 'room'
        self.ledger.attach('DEMO', 'room')
        now = int(time.time())
        for index, (name, text, price) in enumerate([('Mika', '一緒に見たい動画 BV1UT42167xb', 30), ('小夏', '今天也辛苦啦！', 50), ('はる', '次の動画も楽しみです BV1GJ411x7h7', 100)]):
            event = normalize('room', 'sc', dict(id=f'demo-{index}', uid=index + 1, uname=name, message=text, price=price, start_time=now + index), 'DEMO')
            self.ledger.ingest(event, video=True)
        self.ledger.mark('DEMO:room:sc:demo-1', 'circle')  # A deliberately confirmed demo row.
        self.ledger.mark('DEMO:room:sc:demo-2', 'triangle')
        self.ledger.ingest(normalize('room', 'gift', dict(tid='demo-gift', uid=1, uname='Mika', gift_name='小电视', num=1, coin_type='gold', total_coin=50000, timestamp=now), 'DEMO'))
        self.notice.set('DEMO · 模拟数据 / サンプルデータ')

    def close(self):
        if self.update_busy:
            messagebox.showinfo(self.t('update'), self.t('update_working'), parent=self.root)
            return
        if self.collector.running and not messagebox.askyesno(self.t('title'), self.t('close_ask'), parent=self.root): return
        self.closing = True
        if self.translation_worker: self.translation_worker.stop()
        if self.login_dialog: self.login_dialog.close()
        self.save_settings()
        self.collector.stop()
        self.finish_close(time.monotonic() + 25)

    def finish_close(self, deadline):
        # Drain events already received before committing the final TXT snapshot.
        while not self.queue.empty():
            kind, data = self.queue.get_nowait()
            self.handle(kind, data)
        if self.collector.running and time.monotonic() < deadline:
            self.root.after(100, lambda: self.finish_close(deadline))
            return
        try:
            self.ledger.export()
        except OSError:
            if messagebox.askretrycancel(self.t('export'),self.t('export_failed_retry',directory=str(self.ledger.export_directory)),parent=self.root):
                self.root.after(100,lambda:self.finish_close(deadline))
                return
        if self.overlay: self.overlay.close()
        self.ledger.db.close()
        self.root.update_idletasks()
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    directory = data_directory(base, args.data_dir, args.demo)
    # Upstream debug messages may contain raw messages or identity codes.
    logging.getLogger('blivedm').disabled = True
    logging.getLogger('blivedm').setLevel(logging.CRITICAL)
    logging.getLogger('blivedm').addHandler(logging.NullHandler())
    if sys.platform == 'win32':
        shell = ctypes.windll.shell32
        shell.SetCurrentProcessExplicitAppUserModelID('Kokata.SCMaru')
        if getattr(sys, 'frozen', False):
            # In-place updates keep the EXE path, so notify Explorer of the replaced item.
            shell.SHChangeNotify(0x2000, 0x0005, ctypes.c_wchar_p(sys.executable), None)
    root = tk.Tk()
    app = App(root, directory, args.demo)
    root.mainloop()
    if app.update_stage:
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
            updater.launch_update(app.update_stage, directory, app.t('update_reopen'))
        except OSError as error:
            messagebox.showerror(app.t('update'), app.t('update_failed', error=type(error).__name__))


if __name__ == '__main__':
    main()
