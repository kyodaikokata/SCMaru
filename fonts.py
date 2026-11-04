"""Offline font assets shared by browser sources and native preview dropdowns."""
from functools import lru_cache
import json
from pathlib import Path
import os

ROOT = Path(__file__).parent / 'assets/fonts'


@lru_cache(maxsize=1)
def entries():
    path = ROOT / 'manifest.json'
    return json.loads(path.read_text(encoding='utf-8'))['fonts'] if path.is_file() else []


def families():
    return list(dict.fromkeys(e['family'] for e in entries()))


@lru_cache(maxsize=1)
def register_private_fonts():
    """Register bundled faces for this process only; no system font installation."""
    import sys
    if sys.platform != 'win32': return
    import ctypes
    add=ctypes.windll.gdi32.AddFontResourceExW
    add.argtypes=[ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_void_p]
    add.restype=ctypes.c_int
    for file in {e['file'] for e in entries()}: add(str(ROOT/file),0x10,None)


def system_font(size, family='SimHei'):
    from PIL import ImageFont
    folder = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    first = {'Yu Gothic UI': 'YuGothR.ttc', 'Segoe UI': 'segoeui.ttf','Microsoft YaHei UI':'msyh.ttc'}.get(family, 'simhei.ttf')
    for path in [folder / first, folder / 'simhei.ttf', folder / 'msyh.ttc', folder / 'YuGothR.ttc', ROOT / 'NotoSansJP[wght].ttf', folder / 'segoeui.ttf']:
        try: return ImageFont.truetype(str(path), size)
        except OSError: pass
    return ImageFont.load_default(size=size)


def css():
    return '\n'.join('@font-face{font-family:' + json.dumps(e['family']) + ';src:url("/fonts/' + e['file'] + '") format("truetype");font-weight:' + str(e.get('weight', 400)) + ';font-display:swap}' for e in entries())


@lru_cache(maxsize=48)
def preview_png(family, text='剩余SC： 12   日本語 あいうえお   ABC', size=21, weight=400, color='#503847'):
    import io
    from PIL import Image, ImageDraw, ImageFont
    candidates = [e for e in entries() if e['family'] == family]
    if candidates:
        def distance(e):
            value = e.get('weight', 400)
            return 0 if isinstance(value, str) else abs(value-weight)
        entry = min(candidates, key=distance)
        font = ImageFont.truetype(str(ROOT / entry['file']), size)
        try:
            axes = font.get_variation_axes()
            font.set_variation_by_axes([max(a['minimum'], min(a['maximum'], weight)) if b'weight' in a['name'].lower() else a['default'] for a in axes])
        except (OSError, AttributeError): pass
    else:
        font = system_font(size, family)
    image = Image.new('RGBA', (580, 42))
    draw = ImageDraw.Draw(image)
    fallback = system_font(size)
    missing = font.getmask('\U0010ffff')
    missing_key = (missing.size, bytes(missing))
    x = 8
    for char in text:
        glyph = font.getmask(char)
        face = fallback if not char.isspace() and (glyph.size, bytes(glyph)) == missing_key else font
        draw.text((x, 4), char, font=face, fill=color)
        x += face.getlength(char)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


class FontDropdown:
    """A dropdown whose rows render actual bundled-font samples."""
    def __init__(self, parent, variable, palette):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.variable, self.palette = tk, variable, palette
        self.popup = None
        self.button = ttk.Button(parent, text=variable.get() + '  ▾', command=self.open)
        self.trace = variable.trace_add('write', self._label)
        self.button.bind('<Destroy>', self._destroy)

    def _destroy(self, event):
        if event.widget == self.button:
            self.variable.trace_remove('write', self.trace)
            if self.popup and self.popup.winfo_exists(): self.popup.destroy()

    def _label(self, *args):
        if self.button.winfo_exists(): self.button.configure(text=self.variable.get() + '  ▾')

    def open(self):
        import base64
        if self.popup and self.popup.winfo_exists(): self.popup.destroy(); return
        tk, p = self.tk, self.palette
        self.popup = tk.Toplevel(self.button)
        self.popup.wm_overrideredirect(True)
        self.popup.configure(bg=p['line'])
        self.popup.geometry(f'620x430+{self.button.winfo_rootx()}+{self.button.winfo_rooty()+self.button.winfo_height()}')
        self.popup.bind('<Escape>', lambda e: self.popup.destroy())
        canvas = tk.Canvas(self.popup, bg=p['panel'], highlightthickness=0)
        from tkinter import ttk
        scroll = ttk.Scrollbar(self.popup, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); canvas.pack(fill='both', expand=True)
        inner = tk.Frame(canvas, bg=p['panel'])
        canvas.create_window(0, 0, window=inner, anchor='nw', width=600)
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        self.images = []
        choices = families() + ['Microsoft YaHei UI', 'Yu Gothic UI', 'Segoe UI','SimHei']
        for family in choices:
            row = tk.Frame(inner, bg=p['panel'], padx=10, pady=6)
            row.pack(fill='x')
            title = tk.Label(row, text=family, bg=p['panel'], fg=p['fg'], anchor='w', font=('Segoe UI', 10, 'bold'))
            title.pack(fill='x')
            photo = tk.PhotoImage(master=row, data=base64.b64encode(preview_png(family, color=p['fg'])))
            self.images.append(photo)
            sample = tk.Label(row, image=photo, bg=p['panel'], anchor='w')
            sample.pack(fill='x', pady=(4, 0))
            for widget in (row, title, sample):
                widget.bind('<Button-1>', lambda e, f=family: self.choose(f))
                widget.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta/120), 'units'))
        self.popup.transient(self.button.winfo_toplevel())
        self.popup.lift()
        self.popup.focus_set()
        self.popup.bind('<FocusOut>', lambda e: self.popup.after(100, self._dismiss))

    def _dismiss(self):
        if self.popup and self.popup.winfo_exists():
            focused = self.popup.focus_get()
            if focused is None or focused.winfo_toplevel() != self.popup: self.popup.destroy()

    def choose(self, family):
        self.variable.set(family)
        if self.popup and self.popup.winfo_exists(): self.popup.destroy()
