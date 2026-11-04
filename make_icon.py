"""Render the repo-native vector icon into Windows multi-resolution icon assets."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).parent / 'assets'
root.mkdir(exist_ok=True)
s = 8
image = Image.new('RGBA', (64*s, 64*s))
draw = ImageDraw.Draw(image)
pink, border, ink = '#ebcedf', '#d9b3ca', '#b2558b'

def line(points, width=2.8):
    p = [(round(x*s), round(y*s)) for x, y in points]
    draw.line(p, fill=ink, width=round(width*s), joint='curve')
    for x, y in p:
        r = width*s/2
        draw.ellipse((x-r, y-r, x+r, y+r), fill=ink)

draw.rounded_rectangle((4*s, 4*s, 60*s, 60*s), radius=15*s, fill=pink, outline=border, width=round(1.2*s))
draw.rounded_rectangle((15*s, 18*s, 49*s, 41*s), radius=6*s, outline=ink, width=round(2.8*s))
draw.polygon([(23*s, 39*s), (34*s, 39*s), (23*s, 48*s)], fill=pink)
line([(23, 41), (23, 48), (32, 41)])
line([(23, 26), (40, 26)])
line([(23, 33), (32, 33)])
draw.ellipse((35*s, 34*s, 53*s, 52*s), fill=pink, outline=ink, width=round(2.6*s))
line([(40, 43), (43, 46), (48, 40)], 2.6)
image.resize((256, 256), Image.Resampling.LANCZOS).save(root / 'icon.png')
image.save(root / 'icon.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
print(root / 'icon.ico')
