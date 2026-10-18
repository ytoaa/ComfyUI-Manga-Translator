"""Minimal nonempty pixels for tests of adapter responses, not OCR accuracy."""
from PIL import Image


def nonuniform_image(size):
    image=Image.new('RGB',size,'white')
    image.putpixel((0,0),(0,0,0))
    return image
