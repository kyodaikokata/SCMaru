"""Small non-interactive delayed help bubbles for native Tk controls."""
import tkinter as tk


class Tooltip:
    def __init__(self, widget, text, palette):
        self.widget, self.text, self.palette = widget, text, palette
        self.timer = self.window = None
        widget.bind('<Enter>', self.schedule, add='+')
        for event in ('<Leave>', '<ButtonPress>', '<Destroy>', '<FocusOut>'):
            widget.bind(event, self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        self.timer = self.widget.after(550, self.show)

    def show(self):
        self.timer = None
        if not self.widget.winfo_exists(): return
        w = self.window = tk.Toplevel(self.widget)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        p = self.palette
        label = tk.Label(w, text=self.text, justify='left', wraplength=380, padx=12, pady=9,
                         bg=p['input'], fg=p['fg'], relief='solid', borderwidth=1,
                         font=('Microsoft YaHei UI', 10))
        label.pack()
        w.update_idletasks()
        x = max(0, min(self.widget.winfo_rootx(), w.winfo_screenwidth() - w.winfo_reqwidth() - 12))
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        if y + w.winfo_reqheight() > w.winfo_screenheight(): y = self.widget.winfo_rooty() - w.winfo_reqheight() - 6
        w.geometry(f'+{x}+{max(0,y)}')

    def hide(self, event=None):
        if self.timer:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window:
            self.window.destroy()
            self.window = None
