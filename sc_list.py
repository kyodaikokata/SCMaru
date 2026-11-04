"""A wrapping, variable-height SC table with independently scrolling rows."""
from collections import OrderedDict
import tkinter as tk
from tkinter import ttk


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
        self._layout_job = None
        self._viewport_width = None
        self._scroll_job = None
        self._scroll_targets = {}
        self.header = tk.Frame(self, bg=palette['surface'])
        self.header.pack(fill='x')
        self.headings = []
        for col in range(5):
            cell = tk.Frame(self.header, bg=palette['surface'])
            cell.grid(row=0, column=col, sticky='nsew')
            if col in (1, 2, 3):
                label = ttk.Button(cell, width=1, style='Compact.TButton')
                grip = tk.Frame(cell, width=6, bg=palette['surface'])
                grip.pack(side='right', fill='y')
            else:
                label = tk.Label(cell, text='', bg=palette['surface'], fg=palette['fg'],
                                 font=('Microsoft YaHei UI', 10), anchor='center', pady=8)
                grip = label
            label.pack(fill='both', expand=True)
            self.headings.append(label)
            if col < 4:
                grip.configure(cursor='sb_h_double_arrow')
                grip.bind('<Button-1>', lambda e, c=col: self._start_drag(e, c))
                grip.bind('<B1-Motion>', self._drag_column)
                grip.bind('<ButtonRelease-1>', self._end_drag)
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

    def heading(self, key, text, **kwargs):
        index = {'#0': 0, 'time': 1, 'user': 2, 'amount': 3, 'content': 4}[key]
        self.headings[index].configure(text=text, **kwargs)

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
        preview = max(55, min(1200, width + event.x_root - start))
        self.header.columnconfigure(col, minsize=preview)

    def _end_drag(self, event):
        if self._drag is None: return
        col, start, width = self._drag
        self._drag_column(event)
        self._drag = None
        self.widths[col] = max(55, min(1200, width + event.x_root - start))
        if self.widths[col] == width:
            return
        for row in self._records.values():
            if row['divider']: continue
            row['frame'].columnconfigure(col, minsize=self.widths[col])
            row['labels'][col].configure(wraplength=max(30, self.widths[col] - 14))
        self._apply_layout()
        if self.on_resize: self.on_resize()

    def tag_configure(self, name, **kwargs):
        if kwargs: self._tags.setdefault(name, {}).update(kwargs)
        return self._tags.get(name, {})

    def sync(self, entries):
        """Keep unchanged rows and return the frames that need appearance applied."""
        entries = list(entries)
        wanted = {entry[0] for entry in entries}
        self.delete(*(iid for iid in self._records if iid not in wanted))
        created = []
        normal_count = 0
        for iid, text, image, values, tags, translation in entries:
            stripe = normal_count % 2
            if iid != '__processed_separator__':
                normal_count += 1
            key = (text, image, values, tags, translation, stripe, self.row_height, self.font_size)
            row = self._records.get(iid)
            old = row.get('key') if row else None
            if old == key:
                continue
            if old and not row['divider'] and (old[2], old[4], old[6:]) == (values, translation, key[6:]):
                row['labels'][0].configure(text=text, image=image)
                row['text'] = text
                if (old[3], old[5]) != (tags, stripe):
                    bg = self._row_background(False, stripe, tags)
                    fg = self.palette['muted'] if 'removed' in tags else self.palette['fg']
                    row['frame'].configure(bg=bg)
                    row['labels'][-1].master.configure(bg=bg)
                    for label in row['labels']:
                        label.configure(bg=bg, fg=fg)
                    if 'translation_label' in row:
                        row['translation_label'].configure(bg=bg)
                    row['bg'] = bg
                row['key'] = key
                continue
            self.delete(iid)
            self.insert('', 'end', iid, text, image, values, tags, translation, stripe=stripe)
            self._records[iid]['key'] = key
            created.append(self._records[iid]['frame'])
        order = [entry[0] for entry in entries]
        if list(self._records) != order:
            for before, after in zip(reversed(order[:-1]), reversed(order[1:])):
                self._records[before]['frame'].pack(before=self._records[after]['frame'])
            self._records = OrderedDict((iid, self._records[iid]) for iid in order)
        return created

    def _row_background(self, divider, stripe, tags):
        p = self.palette
        bg = p['surface'] if divider else (p['panel'] if stripe == 0 else blend(p['panel'], p['surface']))
        if 'square' in tags:
            tint = '#162b43' if p['bg'] == '#1c1b20' else '#7892b5'
            bg = '#' + ''.join(f'{round(int(bg[i:i+2],16)*.82+int(tint[i:i+2],16)*.18):02x}' for i in (1,3,5))
        return bg

    def insert(self, parent, index, iid, text='', image='', values=(), tags=(),translation='', *, stripe=None):
        p = self.palette
        divider = iid == '__processed_separator__'
        if stripe is None:
            stripe = (len(self._records) - ('__processed_separator__' in self._records)) % 2
        bg = self._row_background(divider, stripe, tags)
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
        if event.width == self._viewport_width:
            return
        self._viewport_width = event.width
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after(75, self._apply_layout)

    def _apply_layout(self):
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
            self._layout_job = None
        self.canvas.itemconfigure(self.window_id, width=max(self.canvas.winfo_width(), sum(self.widths)+180))
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
        self._flush_scroll()
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def get_children(self): return tuple(self._records)
    def exists(self, item): return item in self._records
    def selection(self): return tuple(self._selected)

    def selection_set(self, *items, notify=True):
        if len(items) == 1 and not isinstance(items[0], str): items = tuple(items[0])
        previous = set(self._selected)
        self._selected = [i for i in items if i in self._records and not self._records[i]['divider']]
        current = set(self._selected)
        for iid in previous ^ current:
            self._records[iid]['frame'].configure(highlightthickness=int(iid in current))
        if notify:
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

    def _scroll_view(self, axis, args):
        view = getattr(self.canvas, axis)
        if not args:
            return view()
        if args[0] != 'moveto':
            self._flush_scroll()
            return view(*args)
        self._scroll_targets[axis] = args
        if self._scroll_job is None:
            self._scroll_job = self.after(16, self._flush_scroll)

    def _flush_scroll(self):
        if self._scroll_job is not None:
            self.after_cancel(self._scroll_job)
            self._scroll_job = None
        for axis, args in self._scroll_targets.items():
            getattr(self.canvas, axis)(*args)
        self._scroll_targets.clear()

    def destroy(self):
        for job in (self._layout_job, self._scroll_job):
            if job is not None:
                self.after_cancel(job)
        super().destroy()

    def yview(self, *args): return self._scroll_view('yview', args)
    def yview_moveto(self, value): return self.canvas.yview_moveto(value)
    def xview(self, *args): return self._scroll_view('xview', args)
