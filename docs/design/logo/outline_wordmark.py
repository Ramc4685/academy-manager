"""Outline text from a (variable) font into one SVG path string. Usage: outline.py font text weight tracking_em"""
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
font_path, text, weight, track = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
f = TTFont(font_path)
if "fvar" in f:
    from fontTools.varLib.instancer import instantiateVariableFont
    f = instantiateVariableFont(f, {"wght": weight})
upm = f["head"].unitsPerEm
cmap, gs, hmtx = f.getBestCmap(), f.getGlyphSet(), f["hmtx"]
pen = SVGPathPen(gs)
x = 0
for ch in text:
    g = cmap[ord(ch)]
    gs[g].draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))  # flip y for SVG
    x += hmtx[g][0] + track * upm
x -= track * upm
asc = f["OS/2"].sCapHeight or 700
print(f'{x:.0f} {upm} {asc}')
print(pen.getCommands())
