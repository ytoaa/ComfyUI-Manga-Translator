"""One connected glyph for adapter-response tests, not an OCR accuracy fixture."""
from PIL import Image,ImageDraw


def nonuniform_image(size):
    image=Image.new('RGB',size,'white')
    x,y=size[0]//2,size[1]//2
    ImageDraw.Draw(image).rectangle((x-4,y-6,x+4,y+6),outline='black',width=2)
    return image
