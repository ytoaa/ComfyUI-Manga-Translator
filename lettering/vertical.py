"""Deterministic vertical composition: upright CJK, rotated Latin, two-digit TCY."""
import re
import numpy as np
from PIL import Image, ImageDraw

FORMS = dict(zip('、。「」『』（）［］｛｝【】〈〉《》…', '︑︒﹁﹂﹃﹄︵︶﹇﹈︷︸︻︼︿﹀︽︾︙'))
ROTATE = set('()[]{}<>ー—–-:;')


def tokens(text):
    return re.findall(r'[A-Za-z0-9]+(?:[\x27’][A-Za-z0-9]+)*|[^A-Za-z0-9]', text)


def advance(token, font, cell):
    if len(token) > 1 and token.isascii() and not (token.isdigit() and len(token) == 2):
        return max(cell, float(font.getlength(token)))
    return cell


def layout(text, font, width, height, spacing, tracking, effect):
    cell = sum(font.getmetrics())
    line_step = max(cell*spacing, cell+2*effect+cell*.12)
    columns = []
    for paragraph in text.split('\n'):
        column, used = [], 0.
        for token in tokens(paragraph):
            step = advance(token, font, cell)
            if column and used+tracking+step > height:
                columns.append(column); column, used = [], 0.
            used += (tracking if column else 0)+step
            column.append(token)
        columns.append(column)
    heights = [sum(advance(t, font, cell) for t in c)+max(0,len(c)-1)*tracking for c in columns]
    return columns, (cell+max(0,len(columns)-1)*line_step, max(heights,default=0)), line_step, cell, heights


def draw(canvas, lines, font, origin_x, origin_y, step, cell, tracking, rtl, coverage):
    for index, column in enumerate(lines):
        x = origin_x+(len(lines)-1-index if rtl else index)*step
        y = origin_y
        for token in column:
            height = advance(token, font, cell)
            mapped = FORMS.get(token, token)
            if any(ord(c) not in coverage for c in mapped):
                mapped = token
            bounds = font.getbbox(mapped)
            tile = Image.new('L', (max(1,bounds[2]-bounds[0]+4), max(1,bounds[3]-bounds[1]+4)))
            ImageDraw.Draw(tile).text((2-bounds[0],2-bounds[1]),mapped,font=font,fill=255)
            latin = len(token)>1 and token.isascii() and not (token.isdigit() and len(token)==2)
            if latin or (mapped==token and token in ROTATE):
                tile = tile.rotate(-90,expand=True)
            fit = min(1., (cell-2)/tile.width, (height-2)/tile.height)
            if fit < 1:
                tile = tile.resize((max(1,int(tile.width*fit)),max(1,int(tile.height*fit))),Image.Resampling.LANCZOS)
            left, top = round(x+(cell-tile.width)/2), round(y+(height-tile.height)/2)
            # Lighten rather than replace antialiased neighbours.
            patch = canvas.crop((left,top,left+tile.width,top+tile.height))
            canvas.paste(Image.fromarray(np.maximum(np.asarray(patch),np.asarray(tile))), (left,top))
            y += height+tracking
