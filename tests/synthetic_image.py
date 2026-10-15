"""Invented fixture only; no user screenshot or conversation is embedded."""
from PIL import Image, ImageDraw

def scene(scale=1, theme='light'):
    width,height=800*scale,600*scale
    bg=(235,237,242) if theme=='light' else (35,35,40)
    image=Image.new('RGB',(width,height),bg)
    draw=ImageDraw.Draw(image)
    def box(bounds,color):
        x,y,w,h=[int(v*scale) for v in bounds]
        draw.rounded_rectangle((x,y,x+w-1,y+h-1),radius=10*scale,fill=color)
    box([380,30,390,140],(222,245,247) if theme=='light' else (40,70,70))
    box([20,220,340,70],(255,255,255) if theme=='light' else (65,65,65))
    box([20,330,340,70],(255,255,255) if theme=='light' else (65,65,65))
    return image
