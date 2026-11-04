"""Native gradient reminder badges and soft synthesized notification sounds."""
import math
from pathlib import Path
import struct
import time
import tkinter as tk
import wave


def mix(a,b,t):
    return '#' + ''.join(f'{round(int(a[i:i+2],16)*(1-t)+int(b[i:i+2],16)*t):02x}' for i in (1,3,5))


class ReminderBadge(tk.Canvas):
    def __init__(self, parent, text, kind, palette, command):
        super().__init__(parent,width=224 if kind == 'water' else 244,height=38,bg=palette['bg'],highlightthickness=0,cursor='hand2')
        self.text,self.kind,self.palette,self.command = text,kind,palette,command
        self.base_width=224 if kind=='water' else 244
        self.ui_family,self.ui_scale='Microsoft YaHei UI',1
        self.timer,self.active = None,False
        self.bind('<Button-1>',lambda e: command())
        self.bind('<Return>',lambda e: command())
        self.configure(takefocus=1)
        self.paint()

    def paint(self):
        self.delete('all')
        pulse = (1-math.cos(time.monotonic()*math.pi))/2
        dark = self.palette['bg']=='#1c1b20'
        if self.kind=='water':
            low,high,border = ('#294b64','#4c93b4','#b5e8ff') if dark else ('#e0f2fb','#83bfdf','#287caa')
        else:
            low,high,border = ('#543747','#a96584','#ffd1e6') if dark else ('#fae5ee','#e29bbb','#ad4677')
        base = mix(low,high,pulse)
        width = self.base_width
        # Rounded outer glow, vertical gradient, and a breathing accent border.
        points = [12,2,width-12,2,width-3,5,width-2,12,width-2,27,width-8,35,12,35,3,30,2,12,4,5]
        self.create_polygon(points,smooth=True,fill=mix(base,self.palette['bg'],.18),outline=mix(border,self.palette['bg'],.5),width=3)
        for y in range(7,31):
            color = mix(mix(base,'#ffffff',.13),base,(y-7)/23)
            self.create_line(7,y,width-7,y,fill=color,width=1)
        self.create_polygon(points,smooth=True,fill='',outline=mix(border,base,.1+.35*(1-pulse)),width=1.4+1.2*pulse)
        self.create_text(width/2,18,text=self.text,fill='#ffffff' if dark else '#263c50',font=(self.ui_family,round(9*self.ui_scale),'bold'))
        self.scale('all',0,0,self.ui_scale,self.ui_scale)

    def set_appearance(self,family,scale):
        self.ui_family,self.ui_scale=family,scale
        self.configure(width=round(self.base_width*scale),height=round(38*scale))
        self.paint()

    def set_active(self, active):
        if active and not self.active:
            self.active=True
            self.animate()
        elif not active:
            self.active=False
            if self.timer:
                self.after_cancel(self.timer)
                self.timer=None

    def animate(self):
        if not self.active: return
        self.paint()
        self.timer=self.after(80,self.animate)

    def destroy(self):
        self.set_active(False)
        super().destroy()


def write_sound(path, kind, volume):
    volume = max(0,min(100,float(volume)))/100
    notes = [(659.25,.15),(880,.24)] if kind=='sc' else [(523.25,.18),(659.25,.18),(783.99,.32)]
    rate=22050
    frames=[]
    for frequency,duration in notes:
        count=int(duration*rate)
        for i in range(count):
            envelope=math.sin(math.pi*i/count)**2
            value=math.sin(2*math.pi*frequency*i/rate)*envelope*.18*volume
            frames.append(struct.pack('<h',round(value*32767)))
        frames.append(b'\0\0'*int(.045*rate))
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as sound:
        sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(rate)
        sound.writeframes(b''.join(frames))


class SoundPlayer:
    def __init__(self, directory):
        self.directory=Path(directory)/'sounds'
        self.last=-100.0

    def play(self, kind, volume):
        if volume<=0 or (kind=='sc' and time.monotonic()-self.last<.8): return
        try:
            import winsound
            path=self.directory/f'{kind}-{round(volume)}.wav'
            if not path.is_file(): write_sound(path,kind,round(volume))
            winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
            self.last=time.monotonic()
        except (ImportError,OSError,RuntimeError): pass
