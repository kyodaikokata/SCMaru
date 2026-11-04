"""Apply one UI family/scale while preserving bold, italic and other styles."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from fonts import register_private_fonts


def resolve_family(root,requested):
    register_private_fonts()
    available={name.lower():name for name in tkfont.families(root)}
    return available.get(requested.lower(),available.get('simhei',available.get('黑体','SimHei')))


def apply_widgets(root,family,scale):
    def apply(widget):
        if getattr(widget,'_appearance_applied',None)!=(family,scale):
            if hasattr(widget,'set_appearance'): widget.set_appearance(family,scale)
            try:
                explicit=widget.cget('font')
                if explicit:
                    if not hasattr(widget,'_appearance_base'):
                        widget._appearance_base=tkfont.Font(root=root,font=explicit).actual()
                    values=dict(widget._appearance_base)
                    values.update(family=family,size=round(abs(values['size'])*scale))
                    widget._appearance_font=tkfont.Font(root=root,**values)
                    widget.configure(font=widget._appearance_font)
            except tk.TclError: pass
            if isinstance(widget,tk.Text):
                for tag in widget.tag_names():
                    font=widget.tag_cget(tag,'font')
                    if not font: continue
                    bases=getattr(widget,'_appearance_tag_bases',{})
                    if tag not in bases: bases[tag]=tkfont.Font(root=root,font=font).actual()
                    widget._appearance_tag_bases=bases
                    values=dict(bases[tag]);values.update(family=family,size=round(abs(values['size'])*scale))
                    refs=getattr(widget,'_appearance_tag_fonts',{})
                    refs[tag]=tkfont.Font(root=root,**values);widget._appearance_tag_fonts=refs
                    widget.tag_configure(tag,font=refs[tag])
            widget._appearance_applied=(family,scale)
        for child in widget.winfo_children(): apply(child)
    apply(root)
