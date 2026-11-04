"""One-time three-step welcome: QR login, room ID, LiveHime browser source."""
import tkinter as tk
from tkinter import ttk
from version import VERSION
from login import QRPanel


class StartPage:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.geometry(app.layout.get('start_geometry', '860x800'))
        self.window.minsize(800, 760)
        self.window.bind('<Configure>', lambda e: app.schedule_save() if e.widget == self.window else None, add='+')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.step, self.qr_panel = 0, None
        self.message = tk.StringVar(value=app.t('login_expired') if app.login_expired else '')
        app.ledger.set('welcome_seen', True)
        app.show_start_page.set(False)
        self.render()

    def render(self):
        a, w = self.app, self.window
        for child in w.winfo_children(): child.destroy()
        self.qr_panel = None
        w.title(a.t('start_page') + ' · SCMaru ' + VERSION)
        w.configure(bg=a.palette['bg'])
        outer = ttk.Frame(w, padding=22)
        outer.pack(fill='both', expand=True)
        footer = ttk.Frame(outer)
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        skip_text = ('qr_skip', 'skip_room', 'skip_hime')[self.step]
        ttk.Button(footer, text=a.t(skip_text), command=self.skip).pack(side='left')
        if self.step: ttk.Button(footer, text=a.t('setup_back'), command=self.back).pack(side='left', padx=8)
        ttk.Button(footer, text=a.t('setup_next' if self.step < 2 else 'setup_finish'), command=self.next).pack(side='right')
        ttk.Label(outer, text=f'SC丸 {VERSION} · {self.step+1} / 3', style='Muted.TLabel').pack(anchor='w')
        ttk.Label(outer, text=a.t(('welcome_login', 'welcome_room', 'welcome_hime')[self.step]), style='Title.TLabel').pack(anchor='w', pady=(8, 10))
        ttk.Label(outer, textvariable=self.message, wraplength=780, style='Muted.TLabel').pack(anchor='w', pady=2)
        if self.step == 0:
            row = ttk.Frame(outer)
            row.pack(fill='x')
            ttk.Label(row, text=a.t('setup_language')).pack(side='left', padx=(0,10))
            lang = ttk.Combobox(row, values=['System', '中文', '日本語'], state='readonly', width=15)
            lang.current({'system':0, 'zh':1, 'ja':2}[a.lang_choice])
            lang.pack(side='left')
            def change(e):
                a.change_language(('system','zh','ja')[lang.current()])
                self.render()
            lang.bind('<<ComboboxSelected>>', change)
            ttk.Label(outer, text=a.t('gift_login_note'), wraplength=770).pack(anchor='w', pady=10)
            self.qr_panel = QRPanel(outer, a.t, a.palette, a.save_login)
            self.qr_panel.pack(fill='both', expand=True)
        elif self.step == 1:
            ttk.Label(outer, text=a.t('welcome_room_note'), wraplength=760).pack(anchor='w', pady=18)
            ttk.Label(outer, text=a.t('room')).pack(anchor='w', pady=8)
            entry = ttk.Entry(outer, textvariable=a.room, width=32)
            entry.pack(anchor='w', pady=8)
            entry.bind('<Return>', lambda e: self.next())
            entry.focus_set()
        else:
            ttk.Label(outer, text=a.t('hime_optional'), style='Count.TLabel').pack(anchor='w', pady=14)
            url = a.overlay.url() if a.overlay else ''
            ttk.Entry(outer, textvariable=tk.StringVar(value=url), state='readonly').pack(fill='x', pady=10)
            actions = ttk.Frame(outer)
            actions.pack(fill='x', pady=6)
            ttk.Button(actions, text=a.t('overlay'), command=a.copy_overlay).pack(side='left')
            ttk.Button(actions, text=a.t('overlay_preview'), command=a.open_overlay_preview).pack(side='left', padx=10)
            ttk.Label(outer, text=a.t('hime_tutorial'), wraplength=760, justify='left').pack(anchor='w', pady=24)
        a.apply_appearance()

    def login_completed(self):
        self.message.set(self.app.t('qr_success'))

    def show_expired(self):
        self.message.set(self.app.t('login_expired'))
        if self.step != 0:
            self.step = 0
            self.render()

    def next(self):
        room = self.app.room.get().strip()
        if self.step == 1 and (not room.isdecimal() or int(room) <= 0):
            self.message.set(self.app.t('setup_room_required'))
            return
        self.skip()

    def skip(self):
        self.message.set('')
        if self.step < 2:
            self.step += 1
            self.render()
        else: self.finish(False)

    def back(self):
        self.message.set('')
        self.step = max(0, self.step-1)
        self.render()

    def finish(self, connect=False, skip=False):
        self.app.ledger.set('onboarding_completed', True)
        self.close()
        self.app.main_room_entry.focus_set()

    def close(self):
        self.app.save_settings()
        if self.window.winfo_exists(): self.window.destroy()
        self.app.start_page = None
