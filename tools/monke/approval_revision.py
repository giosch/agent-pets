"""Rebuild approval v2 using the selected key drawings and a catch insert plate.

Run from the checkout root with python -m tools.monke.approval_revision.
Panel count, registration points and exposure times are specified in timing.json.
"""
import json
from xml.etree import ElementTree as ET

from PIL import Image, ImageChops, ImageDraw

from .art import IDS, FUR_IDS
from .pipeline import ROOT, colorize, load_sources, paths_for_frame
from .plate_approval import NEAREST, OUT as ORIGINAL, enlarged, prop

OUT = ROOT / "assets/monke/plate-study/approval-v2"
KEYS = ("neutral", "idea", "swing", "reach", "cuff", "plead", "blink")


def material(rgb):
    r, g, b = rgb
    if min(g, b) > r + 35:
        return 0
    if max(rgb) < 67:
        return IDS["outline"]
    if min(rgb) > 210:
        return IDS["white"]
    if r > 178 and g > 88:
        return IDS["skin.light" if g > 207 else "skin.base" if g > 147 else "skin.shadow"]
    return IDS["fur.shadow" if r < 103 else "fur.base" if r < 150 else "fur.highlight"]


def cut_panel(plate, layout, panel):
    width = plate.width // layout["columns"]
    height = plate.height // layout["rows"]
    row, column = divmod(panel["cell"], layout["columns"])
    x, y = column * width, row * height
    source = plate.crop((x, y, x + width, y + height))
    scale = panel["scale"]
    sample = source.resize((round(width * scale), round(height * scale)), NEAREST)
    ids = Image.new("L", sample.size)
    ids.putdata([material(pixel) for pixel in sample.get_flattened_data()])
    hx, hy = panel["heel"]
    offset = (14 - round(hx * scale), 55 - round(hy * scale))
    frame = Image.new("L", (80, 64))
    frame.paste(ids, offset)
    assert sum(frame.histogram()[1:]) == sum(ids.histogram()[1:]), "Actor clipped"
    button = prop()
    button_mask = button.point(lambda index: 255 if index else 0)
    assert not ImageChops.multiply(frame.crop((59,39,79,56)), button_mask).getbbox()
    frame.paste(button, (59,39), button_mask)
    return frame


def state_svg(drawings, timing, palettes):
    # Each intro exposure plays once. The waiting exposures alone repeat.
    # A static held pose also represents this state under reduced motion.
    defs = "".join(f'<g id="pose-{key}">{paths_for_frame(frame,palettes)}</g>'
                   for key,frame in drawings.items())
    intro = []
    elapsed = 0
    for key, duration in timing["intro"]:
        intro.append(f'<use href="#pose-{key}" visibility="hidden"><set attributeName="visibility" '
                     f'to="visible" begin="{elapsed}ms" dur="{duration}ms"/></use>')
        elapsed += duration
    waiting = timing["waiting"]
    cycle = sum(duration for _, duration in waiting)
    start = 0
    holds = []
    for key, duration in waiting:
        # A repeating discrete opacity sequence per interval, all on the same clock.
        stops = {0: 0, cycle: 0, start: 1, start+duration: 0}
        stops[cycle] = int(start+duration == cycle)
        times = ";".join(f"{t/cycle:.8f}" for t in sorted(stops))
        values = ";".join(str(stops[t]) for t in sorted(stops))
        holds.append(f'<use href="#pose-{key}" opacity="0"><animate attributeName="opacity" '
                     f'begin="{elapsed}ms" dur="{cycle}ms" repeatCount="indefinite" calcMode="discrete" '
                     f'keyTimes="{times}" values="{values}"/></use>')
        start += duration
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 64" width="80" height="64" '
           'shape-rendering="crispEdges"><style>.still{display:none}@media(prefers-reduced-motion:reduce)'
           '{.moving{display:none}.still{display:inline}}</style><defs>'+defs+'</defs>'
           '<g class="moving">'+''.join(intro+holds)+'</g><use class="still" href="#pose-plead"/></svg>')
    ET.fromstring(svg)
    return svg


def main():
    timing = json.loads((OUT/"timing.json").read_text())
    _, palettes = load_sources()
    drawings = {}
    for index, key in enumerate(KEYS, start=1):
        with Image.open(ORIGINAL/f"key-{index}-materials.png") as image:
            drawings[key] = image.copy()
    layout = timing["contact_plate"]
    with Image.open(OUT/layout["file"]) as plate:
        for panel in layout["panels"]:
            key = panel["name"]
            frame = cut_panel(plate.convert("RGB"), layout, panel)
            frame.save(OUT/f"{key}-materials.png")
            drawings[key] = frame
    staged = timing["intro"] + timing["waiting"] + timing["demo_reset"]
    views = {key: colorize(frame, palettes) for key, frame in drawings.items()}
    for palette in ("brown","teal"):
        sprites = {}
        for key,frame in drawings.items():
            rgb = colorize(frame,palettes,palette)
            assert all(a == b or role in FUR_IDS for a,b,role in zip(
                rgb.get_flattened_data(),views[key].get_flattened_data(),frame.get_flattened_data()))
            sprites[key] = enlarged(rgb)
        clip = [sprites[key] for key,_ in staged]
        clip[0].save(OUT/f"approval-{palette}.gif",save_all=True,append_images=clip[1:],
                     duration=[duration for _,duration in staged],loop=0,disposal=2)
    (OUT/"approval.svg").write_text(state_svg(drawings,timing,palettes),encoding="utf-8")
    keys = ["reach","touch","hook","recoil","side_eye","plead"]
    strip = Image.new("RGB",(160*len(keys),150),"#EDE4D2")
    labels = ImageDraw.Draw(strip)
    for i,key in enumerate(keys):
        strip.paste(enlarged(views[key],2),(160*i,0))
        labels.text((160*i+10,129),key.replace("_"," ").upper(),fill="#513023")
    strip.save(OUT/"catch-strip.png")
    print(f"{len(drawings)} drawings. Intro {sum(d for _,d in timing['intro'])} ms. Wait loops independently.")


if __name__ == "__main__":
    main()
