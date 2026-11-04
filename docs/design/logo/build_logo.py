"""Builds every CourtMastr Academy logo SVG from one geometry.

Run from this folder: python3 build_logo.py
Wordmark outlines come from wordmark-paths.txt (Outfit, SIL OFL), produced once with fontTools.
"""
NIGHT, PAPER, INK, VOLT, LINE_GOLD = "#0a0f1c", "#f8fafc", "#0f172a", "#facc15", "#a16207"

# Three chevrons on a 3:4 slope (dx 60, dy 45), 50 apart, 24 thick. Bottom two = levels held, top = the level being earned.
CHEVRONS = ["M68 200L128 155L188 200", "M68 150L128 105L188 150", "M68 100L128 55L188 100"]
SYMBOL_BOX = (60, 40, 135, 170)  # rendered ink bbox on the 256 grid

def stripes(rest, top, sw=24):
    s = f'<g fill="none" stroke-width="{sw}" stroke-linejoin="miter" stroke-miterlimit="10">'
    s += f'<path d="{CHEVRONS[0]}" stroke="{rest}"/><path d="{CHEVRONS[1]}" stroke="{rest}"/>'
    return s + f'<path d="{CHEVRONS[2]}" stroke="{top}"/></g>'

def svg(vb, body, title):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img"><title>{title}</title>{body}</svg>\n'

lines = open("wordmark-paths.txt").read().split("\n")
wm_w, _, wm_cap = map(float, lines[0].split()); wm_d = lines[1]
ac_w, _, ac_cap = map(float, lines[2].split()); ac_d = lines[3]

def word(d, x, y, s, fill):
    return f'<path transform="translate({x:.1f} {y:.1f}) scale({s:.5f})" d="{d}" fill="{fill}"/>'

out = {}
T = "CourtMastr Academy"
# Symbol: dark (primary), light, one-colour
out["symbol-dark.svg"] = svg("0 0 256 256", f'<rect width="256" height="256" rx="56" fill="{NIGHT}"/>' + stripes(PAPER, VOLT), T)
out["symbol-on-dark.svg"] = svg("0 0 256 256", stripes(PAPER, VOLT), T)
out["symbol-on-light.svg"] = svg("0 0 256 256", stripes(INK, LINE_GOLD), T)
out["symbol-black.svg"] = svg("0 0 256 256", stripes("#000", "#000"), T)
out["symbol-white.svg"] = svg("0 0 256 256", stripes("#fff", "#fff"), T)
# App icon tile: full bleed square, no rounded corners (stores apply the mask)
out["app-icon.svg"] = svg("0 0 256 256", f'<rect width="256" height="256" fill="{NIGHT}"/>' + stripes(PAPER, VOLT), T)

# Horizontal lockup: symbol ink box 170 tall -> lockup 256 tall. Wordmark cap height = 0.42 of symbol height.
def horizontal(rest, top, word_fill, sub_fill, bg=None):
    s_cap = 72 / wm_cap; a_cap = 22 / ac_cap
    x0 = 230
    width = x0 + max(wm_w * s_cap, ac_w * a_cap) + 20
    body = f'<rect width="{width:.0f}" height="256" fill="{bg}"/>' if bg else ""
    body += stripes(rest, top)
    body += word(wm_d, x0, 140, s_cap, word_fill)
    body += word(ac_d, x0 + 3, 186, a_cap, sub_fill)
    return svg(f"0 0 {width:.0f} 256", body, T)

def stacked(rest, top, word_fill, sub_fill, bg=None):
    s_cap = 64 / wm_cap; a_cap = 20 / ac_cap
    W = max(wm_w * s_cap, 256) + 120
    body = f'<rect width="{W:.0f}" height="440" fill="{bg}"/>' if bg else ""
    body += f'<g transform="translate({W / 2:.1f} 140) scale(1.15) translate(-128 -125)">' + stripes(rest, top) + "</g>"
    body += word(wm_d, (W - wm_w * s_cap) / 2, 340, s_cap, word_fill)
    body += word(ac_d, (W - ac_w * a_cap) / 2, 384, a_cap, sub_fill)
    return svg(f"0 0 {W:.0f} 440", body, T)

out["lockup-horizontal-light.svg"] = horizontal(INK, LINE_GOLD, INK, LINE_GOLD)
out["lockup-horizontal-dark.svg"] = horizontal(PAPER, VOLT, PAPER, VOLT, NIGHT)
out["lockup-stacked-light.svg"] = stacked(INK, LINE_GOLD, INK, LINE_GOLD)
out["lockup-stacked-dark.svg"] = stacked(PAPER, VOLT, PAPER, VOLT, NIGHT)
out["lockup-horizontal-black.svg"] = horizontal("#000", "#000", "#000", "#000")
out["lockup-horizontal-white.svg"] = horizontal("#fff", "#fff", "#fff", "#fff", "#000")

for name, body in out.items():
    open(name, "w").write(body)
print("\n".join(out))
