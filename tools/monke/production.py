"""Compile the production plates into individual, independently reviewable state packs."""
import argparse
import json
import shutil
from importlib import import_module
from functools import lru_cache

from PIL import Image, ImageDraw
from .art import IDS
from .approval_revision import state_svg
from .pipeline import ROOT, load_sources, colorize
from .plate_approval import enlarged
from .plate_review import prepare

BASE = ROOT / "assets/monke/production"
SOURCES = BASE / "plates"
CUTS = BASE / "cuts"
NN = Image.Resampling.NEAREST


@lru_cache(maxsize=8192)
def classify(rgb):
    r,g,b = rgb
    if min(g,b) > r+38 and g>100:
        return 0
    if max(rgb)<58 or (max(rgb)<89 and max(rgb)-min(rgb)<12):
        return IDS["outline"]
    if min(rgb)>222:
        return IDS["white"]
    if r>g*2.6 and r>b*1.6 and r>150 and g<100:
        return IDS["alert"]
    if g>r*1.15 and g>b*1.17:
        return IDS["leaf"]
    if b>r*1.13:
        return IDS["lens"]
    if g>r*.69 and b<g*.52 and r>146:
        return IDS["yellow" if r>210 else "yellow.shadow"]
    if max(rgb)-min(rgb)<50 or (r>g and g>r*.83 and b>g*.71):
        return IDS["steel" if r<150 else "beige.shadow" if r<206 else "beige"]
    if r>194 and g>96:
        return IDS["skin.light" if g>217 else "skin.base" if g>150 else "skin.shadow"]
    return IDS["fur.shadow" if r<111 else "fur.base" if r<177 else "fur.highlight"]


def cut_cells(path, scale):
    plate = Image.open(path).convert("RGB")
    width,height = plate.width//3,plate.height//2
    output = []
    for i in range(6):
        col,row = i%3,i//3
        cell=plate.crop((col*width,row*height,(col+1)*width,(row+1)*height))
        sample=cell.resize((round(scale*width/height),scale),NN)
        mask=Image.new("L",sample.size)
        mask.putdata([classify(pixel) for pixel in sample.get_flattened_data()])
        output.append(mask)
    # Apply one camera and scale across all drawings, retain authored movement.
    boxes=[im.getbbox() for im in output if im.getbbox()]
    left=min(b[0] for b in boxes); right=max(b[2] for b in boxes)
    bottom=max(b[3] for b in boxes); top=min(b[1] for b in boxes)
    if right-left>78 or bottom-top>60:
        return cut_cells(path,scale-2)
    dx=(80-left-right)//2
    dy=min(62-bottom,max(2-top,56-bottom))
    frames=[]
    for sample in output:
        frame=Image.new("L",(80,64))
        frame.paste(sample,(dx,dy))
        frames.append(frame)
    return frames


def save_json(path,data):
    path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")


def build(name):
    for group in ("cuts","work","acting","energy"):
        source = BASE / f"{group}.json"
        recipes = json.loads(source.read_text()) if source.exists() else {}
        if name in recipes:
            recipe = recipes[name]
            break
    else:
        raise KeyError(f"No exposure recipe for {name}")
    frames=cut_cells(SOURCES/(recipe.get("plate",name)+".png"),recipe.get("scale",69))
    poses={str(i):frame for i,frame in enumerate(frames)}
    # Corrections and passing drawings are authored directly on the material grid.
    from .production_polish import polish
    polish(name,poses)
    if group != "cuts":
        import_module(f".{group}_polish", __package__).polish(name, poses)
    intro=recipe.get("intro",[])
    waiting=recipe["loop"]
    timing={"intro":[[str(k),ms] for k,ms in intro],
            "waiting":[[str(k),ms] for k,ms in waiting]}
    reduced=str(recipe.get("still",waiting[0][0]))
    order=timing["intro"]+timing["waiting"]
    poses={key:poses[key] for key in dict(order)}
    dest=CUTS/name
    dest.mkdir(parents=True,exist_ok=True)
    _,palettes=load_sources()
    save_json(dest/"timing.json",timing)
    svg=state_svg(poses,timing,palettes).replace('class="still" href="#pose-plead"',f'class="still" href="#pose-{reduced}"')
    (dest/"state.svg").write_text(svg,encoding="utf-8")
    for palette in ("brown","teal"):
        imgs=[enlarged(colorize(poses[k],palettes,palette),4) for k,_ in order]
        imgs[0].save(dest/f"{palette}.gif",save_all=True,append_images=imgs[1:],
                     duration=[ms for _,ms in order],loop=0,disposal=2)
    queue=(ROOT/"assets/monke/source/production-queue.md").read_text(encoding="utf-8")
    brief=next(s.split("|")[2].strip() for s in queue.splitlines() if s.startswith(f"| {name} |"))
    spec={"activity":name,"meaning":brief,"tile":[80,64],"svg":"state.svg","brown":"brown.gif","teal":"teal.gif",
          "timing":"timing.json","reference":"assets/concepts/monke/master-reference-v1.png",
          "state_phases":["intro","waiting"],"repeat_phase":"waiting","preview_phases":["intro","waiting"],
          "reduced_pose":reduced,"locked_regions":recipe.get("locks",[])}
    save_json(dest/"candidate.json",spec)
    review=prepare(dest)
    for role in ("art", "motion", "technical"):
        receipt=dest/"review"/f"{role}.json"
        if receipt.is_file():
            previous=json.loads(receipt.read_text(encoding="utf-8-sig")).get("candidate")
            if previous and previous!=review["candidate"]:
                history=dest/"review/history"/previous[:12]
                history.mkdir(parents=True,exist_ok=True)
                shutil.copy2(receipt,history/receipt.name)
    # Neutral blind-review materials. Each row is one exposure on both backgrounds.
    anonymous=ROOT/".debug/monke-blind"/review["candidate"][:12]
    anonymous.mkdir(parents=True,exist_ok=True)
    for palette in ("brown","teal"):
        (anonymous/f"{palette}.gif").write_bytes((dest/f"{palette}.gif").read_bytes())
    w,h=80,64
    board=Image.new("RGB",(448,162*((len(order)+1)//2)),"#292B2A")
    d=ImageDraw.Draw(board)
    for i,(key,ms) in enumerate(order):
        x,y=(i%2)*224,(i//2)*162
        d.text((x+4,y+2),f"{i+1}   {ms} ms",fill="white")
        native=colorize(poses[key],palettes)
        board.paste(native,(x+4,y+24),native)
        teal=colorize(poses[key],palettes,"teal")
        board.paste(teal,(x+4,y+89),teal)
        board.paste(enlarged(native,1),(x+112,y+24))
        board.paste(enlarged(teal,1),(x+112,y+89))
    board.save(anonymous/"sequence.png")
    print(name,review["candidate"][:12],flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("poses",nargs="+")
    for pose in parser.parse_args().poses:
        build(pose)

