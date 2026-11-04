"""Notebook page with a vertical scrollbar and locally scoped mouse wheel."""
import tkinter as tk
from tkinter import ttk


class ScrollPage(ttk.Frame):
    def __init__(self,parent,palette):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,bg=palette['bg'],highlightthickness=0)
        self.bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.content=ttk.Frame(self.canvas,padding=14)
        self.item=self.canvas.create_window(0,0,window=self.content,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.item,width=e.width))
        self.tag='SCMaruScroll'+str(id(self))
        self.bind_class(self.tag,'<MouseWheel>',self.wheel)
        self.content.bind('<Configure>',self.updated)

    def updated(self,event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        def attach(widget):
            tags=widget.bindtags()
            if self.tag not in tags: widget.bindtags((self.tag,)+tags)
            for child in widget.winfo_children(): attach(child)
        attach(self.content);attach(self.canvas)

    def wheel(self,event):
        if self.canvas.winfo_height()<self.content.winfo_reqheight():
            self.canvas.yview_scroll(-int(event.delta/120),'units')
            return 'break'

    def destroy(self):
        self.unbind_class(self.tag,'<MouseWheel>')
        super().destroy()
