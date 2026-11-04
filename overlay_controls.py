"""Native controls for browser-source text, fonts and visual effects."""
import base64
import tkinter as tk
from tkinter import ttk, colorchooser
from fonts import FontDropdown, preview_png


def build_controls(app, parent):
    ttk.Label(parent, text=app.t('template')).pack(anchor='w', pady=(4, 6))
    text_row = ttk.Frame(parent)
    text_row.pack(fill='x', pady=(0, 12))
    ttk.Entry(text_row, textvariable=app.template).pack(side='left', fill='x', expand=True)
    ttk.Button(text_row, text=app.t('overlay'), command=app.copy_overlay).pack(side='right', padx=(10, 0))
    row = ttk.Frame(parent)
    row.pack(fill='x', pady=4)
    ttk.Label(row, text=app.t('font')).pack(side='left', padx=(0, 10))
    selector = FontDropdown(row, app.overlay_font, app.palette)
    selector.button.pack(side='left', fill='x', expand=True)
    ttk.Button(row, text=app.t('color'), command=app.choose_color).pack(side='left', padx=8)
    ttk.Button(row, text=app.t('overlay_preview'), command=app.open_overlay_preview).pack(side='right')
    sample = ttk.Label(parent)
    sample.pack(anchor='w', pady=8)

    def update_sample(*args):
        if not sample.winfo_exists(): return
        try:
            png = preview_png(app.overlay_font.get(), color=app.palette['fg'])
            sample.photo = tk.PhotoImage(master=sample, data=base64.b64encode(png))
            sample.configure(image=sample.photo)
        except (OSError, ValueError): pass
    trace = app.overlay_font.trace_add('write', update_sample)
    sample.bind('<Destroy>', lambda e: app.overlay_font.trace_remove('write', trace) if e.widget == sample else None)
    update_sample()

    def slider(container, label, variable, low, high, decimals=0):
        line = ttk.Frame(container)
        line.pack(fill='x', pady=4)
        ttk.Label(line, text=app.t(label), width=15).pack(side='left')
        value = ttk.Label(line, width=6, anchor='e')
        value.pack(side='right')
        ttk.Scale(line, variable=variable, from_=low, to=high).pack(fill='x', expand=True, padx=8)
        def label_value(*args):
            if value.winfo_exists():
                try: value.configure(text=f'{float(variable.get()):.{decimals}f}')
                except (ValueError, tk.TclError): pass
        watch = variable.trace_add('write', label_value)
        value.bind('<Destroy>', lambda e: variable.trace_remove('write', watch) if e.widget == value else None)
        label_value()

    slider(parent, 'size', app.overlay_size, 10, 240)
    slider(parent, 'weight', app.overlay_effects['weight'], 100, 900)
    styles=ttk.Frame(parent)
    styles.pack(fill='x',pady=6)
    ttk.Checkbutton(styles,text=app.t('italic'),variable=app.overlay_effects['italic_enabled']).pack(side='left')
    def toggle_bold(): app.overlay_effects['weight'].set(700 if app.overlay_effects['bold_enabled'].get() else 400)
    ttk.Checkbutton(styles,text=app.t('bold'),variable=app.overlay_effects['bold_enabled'],command=toggle_bold).pack(side='left',padx=14)
    def sync_bold(*args): app.overlay_effects['bold_enabled'].set(app.overlay_effects['weight'].get()>=700)
    weight_trace=app.overlay_effects['weight'].trace_add('write',sync_bold)
    styles.bind('<Destroy>',lambda e: app.overlay_effects['weight'].trace_remove('write',weight_trace) if e.widget==styles else None)
    sync_bold()
    for effect, specs in [('stroke',[('width',0,12,1)]),('shadow', [('offset', -30, 30, 0), ('blur', 0, 60, 0), ('opacity', 0, 1, 2)]),
                          ('glow', [('blur', 0, 80, 0), ('opacity', 0, 1, 2)])]:
        box = ttk.LabelFrame(parent, padding=8)
        box.pack(fill='x', pady=8)
        header = ttk.Frame(box)
        header.pack(fill='x')
        ttk.Checkbutton(header, text=app.t(effect), variable=app.overlay_effects[effect+'_enabled']).pack(side='left')
        def pick(e=effect):
            variable = app.overlay_effects[e+'_color']
            color = colorchooser.askcolor(color=variable.get(), parent=app.settings_window)[1]
            if color: variable.set(color)
        ttk.Button(header, text=app.t('color'), command=pick).pack(side='right')
        for field, low, high, decimals in specs:
            slider(box, effect+'_'+field, app.overlay_effects[effect+'_'+field], low, high, decimals)
