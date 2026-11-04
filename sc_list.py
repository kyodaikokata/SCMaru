"""A wrapping, variable-height SC table with independently scrolling rows."""
from collections import OrderedDict
import tkinter as tk


def blend(a, b):
    return '#' + ''.join(f'{(int(a[i:i+2],16)+int(b[i:i+2],16))//2:02x}' for i in (1, 3, 5))


class SCList(tk.Frame):
    def __init__(self, master, palette, **kwargs):
        super().__init__(master, bg=palette['panel'], highlightthickness=1, highlightbackground=palette['line'])
        self.palette = palette
        self._records = OrderedDict()
        self._selected = []
        self._tags = {}
        self._callbacks = {}
        self.widths = [100, 128, 92, 65]
        self.row_height = 62
        self.font_size = 10
        self.on_resize = None
        self._drag = None
        self.header = tk.Frame(self, bg=palette['surface'])
        self.header.pack(fill='x')
        self.headings = []
        for col in range(5):
            label = tk.Label(self.header, text='', bg=palette['surface'], fg=palette['fg'],
                             font=('Microsoft YaHei UI', 10), anchor='center', pady=8)
            label.grid(row=0, column=col, sticky='ew')
            self.headings.append(label)
            if col < 4:
                label.configure(cursor='sb_h_double_arrow')
                label.bind('<Button-1>', lambda e, c=col: self._start_drag(e, c))
                label.bind('<B1-Motion>', self._drag_column)
                label.bind('<ButtonRelease-1>', self._end_drag)
            if col < 4: self.header.columnconfigure(col, minsize=self.widths[col])
        self.header.columnconfigure(4, weight=1)
        self.canvas = tk.Canvas(self, bg=palette['panel'], highlightthickness=0, yscrollincrement=22)
        self.canvas.pack(fill='both', expand=True)
        self.inner = tk.Frame(self.canvas, bg=palette['panel'])
        self.window_id = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', self._resize)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<MouseWheel>', self._wheel)

    def bind(self, sequence=None, func=None, add=None):
        if sequence in ('<Button-1>', '<Double-Button-1>', '<Button-2>', '<Double-Button-2>', '<Button-3>', '<Double-Button-3>'):
            self._callbacks[sequence] = func
            return sequence
        return super().bind(sequence, func, add)

    def configure(self, cnf=None, **kwargs):
        for name in ('yscrollcommand', 'xscrollcommand'):
            if name in kwargs: self.canvas.configure(**{name: kwargs.pop(name)})
        if kwargs or cnf is not None: return super().configure(cnf, **kwargs)

    config = configure

    def heading(self, key, text):
        index = {'#0': 0, 'time': 1, 'user': 2, 'amount': 3, 'content': 4}[key]
        self.headings[index].configure(text=text)

    def column(self, key, **kwargs):
        index = {'#0': 0, 'time': 1, 'user': 2, 'amount': 3, 'content': 4}[key]
        if index < 4:
            # Metadata stays compact so most width belongs to wrapped SC text.
            value = max(55, min(1200, kwargs.get('width', self.widths[index])))
            self.widths[index] = value
            self.header.columnconfigure(index, minsize=value)

    def _start_drag(self, event, col):
        self._drag = (col, event.x_root, self.widths[col])

    def _drag_column(self, event):
        if self._drag is None: return
        col, start, width = self._drag
        self.widths[col] = max(55, min(1200, width + event.x_root - start))
        self.header.columnconfigure(col, minsize=self.widths[col])
        for row in self._records.values():
            if row['divider']: continue
            row['frame'].columnconfigure(col, minsize=self.widths[col])
            row['labels'][col].configure(wraplength=self.widths[col] - 14)
            self._wrap_row(row)
        self.canvas.itemconfigure(self.window_id, width=max(self.canvas.winfo_width(), sum(self.widths)+180))

    def _end_drag(self, event):
        self._drag = None
        if self.on_resize: self.on_resize()

    def tag_configure(self, name, **kwargs):
        if kwargs: self._tags.setdefault(name, {}).update(kwargs)
        return self._tags.get(name, {})

    def insert(self, parent, index, iid, text='', image='', values=(), tags=(),translation=''):
        p = self.palette
        divider = iid == '__processed_separator__'
        normal_count = sum(not r['divider'] for r in self._records.values())
        bg = p['surface'] if divider else (p['panel'] if normal_count % 2 == 0 else blend(p['panel'], p['surface']))
        if 'square' in tags:
            tint = '#162b43' if p['bg'] == '#1c1b20' else '#7892b5'
            bg = '#' + ''.join(f'{round(int(bg[i:i+2],16)*.82+int(tint[i:i+2],16)*.18):02x}' for i in (1,3,5))
        frame = tk.Frame(self.inner, bg=bg, highlightbackground=p['green'], highlightthickness=0)
        frame.pack(fill='x')
        row = dict(frame=frame, values=values, text=text, bg=bg, divider=divider, labels=[])
        self._records[iid] = row
        if divider:
            label = tk.Label(frame, text='  ' + text, bg=bg, fg=p['muted'], font=('Microsoft YaHei UI', 10, 'bold'), anchor='w', pady=9)
            label.pack(fill='x')
            self._bind_row(label, iid, '#0')
        else:
            fg = p['muted'] if 'removed' in tags else p['fg']
            for col, value in enumerate((text,) + tuple(values)):
                cell=frame
                if col==4:
                    cell=tk.Frame(frame,bg=bg)
                    cell.grid(row=0,column=col,sticky='nsew')
                label = tk.Label(cell, text=value, bg=bg, fg=fg, font=('Microsoft YaHei UI', self.font_size),
                                 anchor='nw', justify='left', padx=7, pady=12,
                                 image=image if col == 0 else '', compound='left')
                if col==4: label.pack(fill='x',anchor='nw')
                else: label.grid(row=0, column=col, sticky='nsew')
                if col < 4:
                    frame.columnconfigure(col, minsize=self.widths[col], weight=0)
                    label.configure(wraplength=max(30, self.widths[col]-14))
                    label.grid_propagate(False)
                else:
                    frame.columnconfigure(col, weight=1)
                self._bind_row(label, iid, f'#{col}')
                row['labels'].append(label)
                if col==4 and translation:
                    translated=tk.Label(cell,text=translation,bg=bg,fg=p['muted'],font=('Microsoft YaHei UI',self.font_size,'italic'),anchor='nw',justify='left',padx=7,pady=5)
                    translated.pack(fill='x',anchor='nw')
                    row['translation_label']=translated
                    self._bind_row(translated,iid,'#4')
            frame.rowconfigure(0, minsize=self.row_height)
        self._wrap_row(row)
        return iid

    def _wrap_row(self, row):
        if not row['divider']:
            width = max(180, self.canvas.winfo_width() - sum(self.widths) - 16)
            row['labels'][-1].configure(wraplength=width)
            if row.get('translation_label'): row['translation_label'].configure(wraplength=width)

    def _resize(self, event):
        self.canvas.itemconfigure(self.window_id, width=max(event.width, sum(self.widths)+180))
        for row in self._records.values(): self._wrap_row(row)

    def _bind_row(self, label, iid, column):
        for seq in ('<Button-1>', '<Double-Button-1>', '<Button-2>', '<Double-Button-2>', '<Button-3>', '<Double-Button-3>'):
            label.bind(seq, lambda e, s=seq, i=iid, c=column: self._mouse(e, s, i, c))
        label.bind('<MouseWheel>', self._wheel)

    def _mouse(self, event, sequence, iid, column):
        event.item_id, event.column_id = iid, column
        callback = self._callbacks.get(sequence)
        return callback(event) if callback else None

    def _wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def get_children(self): return tuple(self._records)
    def exists(self, item): return item in self._records
    def selection(self): return tuple(self._selected)

    def selection_set(self, *items):
        if len(items) == 1 and not isinstance(items[0], str): items = tuple(items[0])
        self._selected = [i for i in items if i in self._records and not self._records[i]['divider']]
        for iid, row in self._records.items(): row['frame'].configure(highlightthickness=1 if iid in self._selected else 0)
        self.event_generate('<<TreeviewSelect>>')

    def focus(self, item=None): return item

    def delete(self, *items):
        for iid in items:
            if iid in self._records: self._records.pop(iid)['frame'].destroy()
        self._selected = [i for i in self._selected if i in self._records]

    def identify_region(self, x, y):
        return 'heading' if y < self.header.winfo_height() else ('tree' if x < self.widths[0] else 'cell')

    def identify_column(self, x):
        offset = 0
        for col, width in enumerate(self.widths):
            offset += width
            if x < offset: return f'#{col}'
        return '#4'

    def identify_row(self, y):
        actual = self.canvas.canvasy(y-self.header.winfo_height())
        for iid, row in self._records.items():
            frame = row['frame']
            if frame.winfo_y() <= actual < frame.winfo_y()+frame.winfo_height(): return iid
        return ''

    def yview(self, *args): return self.canvas.yview(*args)
    def yview_moveto(self, value): return self.canvas.yview_moveto(value)
    def xview(self, *args): return self.canvas.xview(*args)
