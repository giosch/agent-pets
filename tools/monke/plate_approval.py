"""Cut the six approval drawings from a generated plate and stage them at game size.

Run from the repo root with python -m tools.monke.plate_approval (requires Pillow).
The reviewed anchors and cleanup below belong to this specific plate.
"""
from PIL import Image, ImageDraw
from .art import IDS, FUR_IDS
from .pipeline import ROOT, load_sources, colorize, animated_svg

OUT = ROOT / "assets/monke/plate-study/approval"
# Left heel coordinates after sampling each 512px panel at one common scale.
HEELS = [13, 12, 9, 8, 7, 7]
NEAREST = Image.Resampling.NEAREST


def actor(panel, number, passing=False):
    panel = panel.resize((69, 69), NEAREST).convert("RGB")
    grid = Image.new("L", panel.size)
    for y in range(69):
        for x in range(69):
            r, g, b = panel.getpixel((x, y))
            if g > r + 35 and b > r + 35:
                continue
            if number == 2 and y <= 47:
                # Erase the stray rear tail. Follow the outside of the far knuckle.
                if (y < 30 and x < 20) or (30 <= y < 38 and x < 11) or (38 <= y <= 47 and x < 10):
                    continue
            if max(r, g, b) < 67:
                material = "outline"
            elif min(r, g, b) > 210:
                material = "white"
            elif r > 178 and g > 88:
                material = "skin.light" if g > 207 else "skin.base" if g > 147 else "skin.shadow"
            else:
                material = "fur.shadow" if r < 103 else "fur.base" if r < 150 else "fur.highlight"
            grid.putpixel((x, y), IDS[material])
    if number == 2:
        ImageDraw.Draw(grid).line([(11,38),(10,42),(10,47)],fill=IDS["outline"])
        if passing:
            # Swing the reaching arm about its shoulder on the way down.
            # The original plate jumps directly from finger-up to full extension.
            arm = Image.new("L", grid.size)
            region = (42, 31, 68, 40)
            arm.paste(grid.crop(region), region[:2])
            grid.paste(0, region)
            rotated = arm.rotate(26, resample=NEAREST, center=(42, 34))
            grid.paste(rotated, mask=rotated.point(lambda p: 255 if p else 0))
    # The registration is independent of head/arm extents.
    out = Image.new("L", (80, 64))
    floor = grid.getbbox()[3] - 1
    out.paste(grid, (14 - HEELS[number], 55 - floor))
    return out


def prop():
    # Extract the stationary T2 pedestal from its isolated prop-library entry.
    sheet = Image.open(ROOT/"assets/concepts/monke/master-reference-v1.png")
    rgb = sheet.crop((374, 618, 494, 702)).resize((20, 17), NEAREST).convert("RGB")
    # Only remove the cream paper connected to the crop boundary.
    img = rgb.copy()
    for x in range(rgb.width):
        for y in (0, rgb.height-1):
            if min(img.getpixel((x,y))) > 142:
                ImageDraw.floodfill(img,(x,y),(0,255,255),thresh=75)
    indices = Image.new("L", rgb.size)
    for y in range(rgb.height):
        for x in range(rgb.width):
            r,g,b = img.getpixel((x,y))
            if (r,g,b) == (0,255,255):
                continue
            m = ("outline" if r < 75 else "alert" if r > g*1.6 and g < 138
                 else "yellow" if r > 155 and g > 120 and b < 85
                 else "white" if y < 9 and r > 213 else "beige" if r > 188 else "beige.shadow")
            indices.putpixel((x,y), IDS[m])
    return indices


def enlarged(image, scale=4):
    base = Image.new("RGB", image.size, "#EDE4D2")
    base.paste(image, mask=image.getchannel("A"))
    return base.resize((base.width*scale,base.height*scale), NEAREST)


def main():
    plate = Image.open(OUT/"plate.png")
    assert plate.size == (1536,1024)
    _, palettes = load_sources()
    button = prop()
    drawings = []
    for i,(n,passing) in enumerate([(0,False),(1,False),(2,True),(2,False),(3,False),(4,False),(5,False)]):
        x,y = (n%3)*512,(n//3)*512
        frame = actor(plate.crop((x,y,x+512,y+512)), n, passing)
        at = (59,39)
        for py in range(button.height):
            for px in range(button.width):
                if button.getpixel((px,py)):
                    assert not frame.getpixel((at[0]+px,at[1]+py)), (n,px,py)
        frame.paste(button, at, button.point(lambda p: 255 if p else 0))
        drawings.append(frame)
        frame.save(OUT/f"key-{i+1}-materials.png")
        colorize(frame,palettes).save(OUT/f"key-{i+1}.png")
    # Anticipation -> quick reach -> catch -> eye contact -> sleepy blink -> wait.
    # The loop returns through the raised finger, which reads as a withdrawal.
    order = [0,1,2,3,4,5,6,5,4,2,1,0]
    ms = [620,310,80,130,210,790,120,1200,200,100,180,280]
    for palette in ("brown","teal"):
        sprites = [colorize(drawings[i],palettes,palette) for i in order]
        for n,im in zip(order,sprites):
            base = colorize(drawings[n],palettes)
            for material, a, b in zip(drawings[n].get_flattened_data(),base.get_flattened_data(),im.get_flattened_data()):
                assert a == b or material in FUR_IDS
        views = [enlarged(im) for im in sprites]
        views[0].save(OUT/f"approval-{palette}.gif",save_all=True,append_images=views[1:],duration=ms,loop=0,disposal=2)
    (OUT/"approval.svg").write_text(animated_svg([drawings[i] for i in order],ms,palettes,"approval_plate"),encoding="utf-8")
    proof=Image.new("RGB",(len(drawings)*160,128),"#EDE4D2")
    for i,frame in enumerate(drawings):
        proof.paste(enlarged(colorize(frame,palettes),2),(160*i,0))
    proof.save(OUT/"key-poses.png")
    print("Six registered drawings and one passing pose. Palette isolation and stationary prop verified.")


if __name__ == "__main__":
    main()

