"""Build the local review gallery and export the fully accepted Habitat character."""
import argparse
import json
from html import escape
from pathlib import Path
from os.path import relpath
from PIL import Image, ImageDraw, ImageFont

from .batch import run
from .production import BASE, CUTS, ROOT
from .plate_review import BACKDROP


def assets(name):
    directory = ROOT/"assets/monke/plate-study/approval-v3" if name == "approval" else CUTS/name
    spec = json.loads((directory/"candidate.json").read_text(encoding="utf-8"))
    return directory, spec


def export_reel(status):
    frames = []
    durations = []
    font = ImageFont.load_default(size=18)
    for index, name in enumerate(status, 1):
        directory, spec = assets(name)
        timing = json.loads((directory / spec["timing"]).read_text())
        remaining = sum(ms for phase in spec["state_phases"] for _, ms in timing[phase])
        with Image.open(directory / spec["brown"]) as clip:
            for number in range(clip.n_frames):
                clip.seek(number)
                duration = min(remaining, clip.info["duration"])
                artwork = clip.convert("RGB").resize((320, 256), Image.Resampling.NEAREST)
                frame = Image.new("RGB", (320, 292), BACKDROP)
                frame.paste(artwork)
                draw = ImageDraw.Draw(frame)
                draw.fontmode = "1"
                draw.text((14, 261), name.replace("_", " ").title(), font=font, fill="#261C19")
                draw.text((306, 261), f"{index} / {len(status)}", font=font, fill="#513023", anchor="ra")
                frames.append(frame)
                durations.append(duration)
                remaining -= duration
                if remaining == 0:
                    break
        if remaining:
            raise ValueError(f"Preview ended early for {name}")
    frames[0].save(BASE / "all-animations.gif", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, disposal=1)


def gallery(status):
    cards = []
    for name, result in status.items():
        if result == "awaiting_artwork":
            continue
        directory, spec = assets(name)
        paths = {key: Path(relpath(directory/spec[key], BASE)).as_posix() for key in ("brown","teal","svg")}
        label = "Approved" if result == "accepted_for_batch" else result.replace("_", " ").capitalize()
        cards.append(f'''<article><h2>{escape(name.replace("_"," ").title())}</h2>
<figure><img width="160" height="128" src="{paths["svg"]}" data-state="{paths["svg"]}" data-brown="{paths["brown"]}" data-teal="{paths["teal"]}" alt="{escape(spec["meaning"], quote=True)}"></figure>
<p>{escape(spec["meaning"])}</p><small>{label}</small> <a href="{paths["svg"]}">Open state</a></article>''')
    total=sum(v=="accepted_for_batch" for v in status.values())
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monke animation review</title><style>
*{box-sizing:border-box}body{max-width:1280px;margin:0 auto;padding:24px;font:16px system-ui;background:#f1e9d8;color:#291d19}
h1{margin-bottom:4px}header{display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}nav{margin:18px 0;display:flex;gap:14px;flex-wrap:wrap;align-items:center}
select,button{font:inherit;padding:4px 8px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px}
article{border:1px solid #b2a48c;padding:14px;border-radius:6px}h2{font-size:18px;margin:0 0 8px}figure{margin:0;display:grid;place-items:center;background:#eae0cc}
img{image-rendering:pixelated;display:block}body.dark figure{background:#373632}article p{font-size:14px;min-height:2.8em}small{font-weight:650}a{color:inherit;float:right;font-size:13px}</style>
<header><h1>Monke animation review</h1><span>__COUNT__ approved</span></header>
<nav><label>Playback <select id="mode"><option value="state">Habitat state</option><option value="brown">Brown demo</option><option value="teal">Teal demo</option></select></label>
<label>Scale <select id="scale"><option>1</option><option selected>2</option><option>3</option></select>×</label>
<label><input id="dark" type="checkbox"> Dark stage</label><button id="replay">Replay</button>__REEL__</nav>
<main>__CARDS__</main><script>
const imgs=[...document.images],mode=document.querySelector('#mode'),scale=document.querySelector('#scale');
function play(){for(const img of imgs)img.src=img.dataset[mode.value]+'?replay='+Date.now()}
mode.onchange=play;document.querySelector('#replay').onclick=play;
scale.onchange=()=>imgs.forEach(i=>{i.width=80*scale.value;i.height=64*scale.value});
document.querySelector('#dark').onchange=e=>document.body.classList.toggle('dark',e.target.checked);
</script></html>'''
    reel='<a href="all-animations.gif">Play all 35 in sequence</a>' if (BASE/"all-animations.gif").is_file() else ""
    (BASE/"index.html").write_text(page.replace("__COUNT__",f"{total} / {len(status)}").replace("__REEL__",reel).replace("__CARDS__","\n".join(cards)), encoding="utf-8")


def export(status):
    from clawd_tank_habitat.themes import Pack, read_archive
    if any(result != "accepted_for_batch" for result in status.values()):
        raise ValueError("Every state needs current art, motion and browser passes before export")
    palettes = json.loads((BASE.parent/"source/palettes.json").read_text())["fur"]
    paths={}
    for name in status:
        directory,spec=assets(name)
        paths[name]=str((directory/spec["svg"]).relative_to(ROOT/"assets").as_posix())
    manifest={"id":"monke","name":"Monke","kind":"character","poses":paths,"fur_palettes":list(palettes.values())}
    pack=Pack.load(manifest,lambda path:(ROOT/"assets"/path).read_text(encoding="utf-8"))
    archive=BASE/"monke.zip"
    pack.archive(archive)
    restored=read_archive(archive)
    for name in status:
        for variant in range(len(palettes)):
            if restored.svg(name,variant)!=pack.svg(name,variant):
                raise ValueError(f"Changed artwork during export: {name}")
    export_reel(status)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--export",action="store_true")
    options=parser.parse_args()
    statuses=run("audit")
    if options.export:
        export(statuses)
    gallery(statuses)
