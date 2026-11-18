"""Build/review the Monke pilot. Run: python -m tools.monke.pipeline build.

The compiler never calls an image/model API. Agents edit semantic artwork and
briefs, build, inspect previews and revise. Later batches require explicit review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw

from .art import MATERIALS, FUR_IDS, IDS, draw_frame

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets/monke/source"
DEFAULT_OUT = ROOT / "assets/monke/build"
PILOT = {"idle", "coding", "approval", "walking", "ready"}
XMLNS = "http://www.w3.org/2000/svg"


def load_sources():
    return (json.loads((SOURCE / "animations.json").read_text()),
            json.loads((SOURCE / "palettes.json").read_text()))


def fingerprint():
    paths = [SOURCE / "animations.json", SOURCE / "palettes.json",
             Path(__file__), Path(__file__).with_name("art.py"),
             ROOT / "host/clawd_tank_habitat/themes.py"]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def colorize(materials, palettes, name="brown"):
    colors = {**palettes["fixed"], **palettes["fur"][name]}
    rgba = [(0, 0, 0, 0)] + [tuple(bytes.fromhex(colors[m][1:])) + (255,) for m in MATERIALS[1:]]
    output = Image.new("RGBA", materials.size)
    output.putdata([rgba[p] for p in materials.get_flattened_data()])
    return output


def paths_for_frame(frame, palettes):
    """Lossless row-run SVG paths: one path per material, integer coordinates."""
    commands = {m: [] for m in MATERIALS[1:]}
    pixels = frame.load()
    for y in range(frame.height):
        x = 0
        while x < frame.width:
            index, start = pixels[x, y], x
            while x < frame.width and pixels[x, y] == index:
                x += 1
            if index:
                length = x - start
                commands[MATERIALS[index]].append(f"M{start},{y}h{length}v1h-{length}z")
    colors = {**palettes["fixed"], **palettes["fur"]["brown"]}
    return "".join(f'<path data-material="{m}" fill="{colors[m]}" d="{"".join(runs)}"/>'
                   for m, runs in commands.items() if runs)


def animated_svg(frames, durations, palettes, name):
    total = sum(durations)
    rules, groups = [], []
    time = 0
    for i, (frame, duration) in enumerate(zip(frames, durations)):
        start, end = 100*time/total, 100*(time+duration)/total
        stops = {0.0: 0, 100.0: 0, start: 1, end: 0}
        # The next cycle selects frame zero, no duplicate invisible boundary frame.
        if i == len(frames)-1:
            stops[100.0] = 1
        keyframes = "".join(f"{p:.6f}%{{opacity:{v}}}" for p,v in sorted(stops.items()))
        key = f"monke_{name}_f{i}"
        rules.append(f"@keyframes {key}{{{keyframes}}}.{key}{{opacity:0;animation:{key} {total}ms steps(1,end) infinite}}")
        groups.append(f'<g class="frame {key}'+(' first' if i == 0 else '')+f'" data-frame="{i}">{paths_for_frame(frame,palettes)}</g>')
        time += duration
    rules.append("@media(prefers-reduced-motion:reduce){.frame{animation:none;opacity:0}.first{opacity:1}}")
    return (f'<svg xmlns="{XMLNS}" viewBox="0 0 80 64" width="80" height="64" '
            f'shape-rendering="crispEdges"><style>{"".join(rules)}</style>{"".join(groups)}</svg>')


def validate(briefs, palettes, rendered):
    """Fail the build on measurable errors. Visual review stays explicitly pending."""
    errors = []
    if set(briefs["animations"]) != PILOT:
        errors.append("Only the five pilot animations are authorized in this batch")
    if briefs["pixel_size"] != [80,64] or briefs["fps"] != 8:
        errors.append("Pilot uses an 80x64 logical grid at 8 fps")
    if set(palettes["fixed"]) != set(MATERIALS[1:]) - {"fur.shadow","fur.base","fur.highlight"}:
        errors.append("Fixed material table is incomplete or contains fur")
    checks = []
    fur_roles = {"fur.shadow", "fur.base", "fur.highlight"}
    for name, palette in palettes["fur"].items():
        if set(palette) != fur_roles:
            errors.append(f"{name}: only three fur roles may vary")
    for name,(frames,durations) in rendered.items():
        changed_count = 0
        if frames[0].tobytes() != frames[-1].tobytes():
            errors.append(f"{name}: loop endpoint mismatch")
        if len({f.tobytes() for f in frames}) < 2:
            errors.append(f"{name}: animation has no movement")
        if len(frames) != len(durations) or any(d <= 0 or d % 125 for d in durations):
            errors.append(f"{name}: invalid frame timing")
        for i,frame in enumerate(frames):
            if frame.size != (80,64) or max(frame.get_flattened_data()) >= len(MATERIALS):
                errors.append(f"{name}/{i}: invalid dimensions/material")
            bounds = frame.getbbox()
            if not bounds or bounds[0] == 0 or bounds[1] == 0 or bounds[2] == 80 or bounds[3] == 64:
                errors.append(f"{name}/{i}: artwork touches canvas edge")
            baseline = list(colorize(frame,palettes).get_flattened_data())
            for palette_name in palettes["fur"]:
                variant = colorize(frame,palettes,palette_name)
                for material, a, b in zip(frame.get_flattened_data(),baseline,variant.get_flattened_data()):
                    if a != b:
                        changed_count += 1
                        if material not in FUR_IDS:
                            errors.append(f"{name}/{i}: non-fur pixel changed in {palette_name}")
                if any(pixel[3] not in (0,255) for pixel in variant.get_flattened_data()):
                    errors.append(f"{name}/{i}: fractional alpha")
            if name == "approval":
                # Complete prop region remains identical in all frames: never pressed.
                if frame.crop((59,36,77,56)).tobytes() != frames[0].crop((59,36,77,56)).tobytes():
                    errors.append(f"approval/{i}: button region changed")
        checks.append({"animation":name,"frames":len(frames),"duration_ms":sum(durations),
                       "palette_changed_pixels":changed_count,"loop_endpoints_match":True})
    return {"automated":"passed" if not errors else "failed", "errors":errors,
            "checks":checks,"visual_review":"pending_user", "next_batch":"blocked_until_review"}


def rgb565_export(frames, durations, palettes, name):
    """RLE material IDs + swappable RGB565 tables; no firmware changes implied."""
    runs, offsets = [], []
    for frame in frames:
        offsets.append(len(runs))
        previous, count = None,0
        for material in frame.get_flattened_data():
            if material != previous and count:
                runs.extend((count, previous))
                count = 0
            previous = material
            count += 1
        runs.extend((count,previous))
    offsets.append(len(runs))
    def array(ctype, label, values):
        return f"static const {ctype} monke_{name}_{label}[] = {{"+",".join(map(str,values))+"};\n"
    output = "#pragma once\n#include <stdint.h>\n// RLE pairs: count, MATERIAL ID. Not the legacy RGB565 RLE format.\n"
    output += "// index 0 is transparent; remaining entries are RGB565. Select a palette at draw time.\n"
    output += f"#define MONKE_{name.upper()}_WIDTH 80\n#define MONKE_{name.upper()}_HEIGHT 64\n"
    output += array("uint16_t","runs",runs) + array("uint32_t","offsets",offsets)
    output += array("uint16_t","durations_ms",durations)
    for palette_name in palettes["fur"]:
        colors = {**palettes["fixed"],**palettes["fur"][palette_name]}
        values = [0]
        for material in MATERIALS[1:]:
            r,g,b = bytes.fromhex(colors[material][1:])
            values.append(((r&248)<<8)|((g&252)<<3)|(b>>3))
        output += array("uint16_t",f"palette_{palette_name}",values)
    return output


def preview_html(briefs, palettes, svg_data, report):
    payload = json.dumps({"briefs":briefs,"palettes":palettes,"svgs":svg_data,"report":report}).replace("</","<\\/")
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Monke — pilot review</title><style>
:root{color-scheme:dark}body{margin:0;background:#182327;color:#f4e7c8;font:15px system-ui}main{max-width:1180px;margin:auto;padding:32px}h1{font-size:34px;margin:0 0 8px}p{color:#bac5c3;line-height:1.6}header{margin-bottom:24px}.controls{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:24px 0}button,select{font:inherit;background:#34484b;color:#fff;border:1px solid #617477;border-radius:6px;padding:8px}#cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}article{background:#233337;border:1px solid #425558;border-radius:12px;padding:18px}h2{margin:0 0 4px;text-transform:capitalize}.stage{display:flex;justify-content:center;align-items:center;min-height:272px;background:var(--stage,#eee4ce);border-radius:8px;margin:16px 0;overflow:auto}.stage svg,.tiny svg{image-rendering:pixelated;flex-shrink:0}.tiny{display:flex;gap:12px;align-items:center;height:72px}.tiny svg{width:80px;height:64px;background:var(--stage,#eee4ce)}.meta{font-size:12px;color:#bac5c3}.scrub{width:100%}.badge{display:inline-block;border:1px solid #6b865a;color:#c6dea8;padding:4px 10px;border-radius:20px;font-size:12px}.swatches{display:flex;gap:5px}.swatches span{width:20px;height:20px;border:1px solid #aaa;border-radius:3px}footer{margin-top:24px;color:#bac5c3}input{accent-color:#f6cf35}</style>
<main><header><span class="badge">PILOT 01 · WAITING FOR YOUR REVIEW</span><h1>Confidently incompetent.</h1><p>Five Monke animations · E proportions + B attitude · T2 hardware · P1 pixels.<br>Only the dark fur and tail change palette. Face, belly, hands, feet, outlines and props stay fixed.</p></header>
<div class="controls"><label>Fur <select id="palette"></select></label><label>Zoom <select id="zoom"><option value="1">1×</option><option value="2">2×</option><option value="4" selected>4×</option><option value="6">6×</option></select></label><label>Backdrop <select id="backdrop"><option value="#eee4ce">Light</option><option value="#182327">Dark</option><option value="#727a78">Gray</option></select></label><button id="toggle">Pause all</button><span class="swatches" id="swatches"></span></div><section id="cards"></section><footer>80 × 64 logical pixels · 8 fps timing grid · transparent exports · no smoothing.<br>Scrub a paused animation to inspect contact and silhouette. Hardware exports use material-index RLE with RGB565 palette tables; device integration is a separate step.</footer></main>
<script>const data=PAYLOAD;let paused=matchMedia('(prefers-reduced-motion: reduce)').matches;const cards=[];for(const name of Object.keys(data.palettes.fur)){palette.add(new Option(name,name))}for(const [name,brief] of Object.entries(data.briefs.animations)){const card=document.createElement('article');card.innerHTML=`<h2>${name}</h2><div class="meta">${brief.frames.length} poses · ${brief.frames.reduce((n,f)=>n+f.ticks*125,0)/1000}s loop</div><div class="stage">${data.svgs[name]}</div><div class="tiny">${data.svgs[name]}<span class="meta">Actual size · 1×</span></div><p>${brief.story}</p><label class="meta">Inspect frame <output>0</output><input aria-label="${name} frame" class="scrub" type="range" min="0" max="${brief.frames.length-1}" value="0"></label>`;cards.push(card);document.querySelector('#cards').append(card);card.querySelector('input').oninput=e=>{paused=true;setPlayback();card.querySelector('output').value=e.target.value;for(const frame of card.querySelectorAll('[data-frame]'))frame.style.opacity=frame.dataset.frame===e.target.value?'1':'0'}}function setPlayback(){toggle.textContent=paused?'Play all':'Pause all';for(const frame of document.querySelectorAll('[data-frame]')){frame.style.animation=paused?'none':'';frame.style.opacity=paused?(frame.dataset.frame==='0'?'1':'0'):''}}function update(){const colors=data.palettes.fur[palette.value];for(const el of document.querySelectorAll('[data-material]')){if(colors[el.dataset.material])el.setAttribute('fill',colors[el.dataset.material])}for(const svg of document.querySelectorAll('.stage svg')){svg.style.width=80*Number(zoom.value)+'px';svg.style.height=64*Number(zoom.value)+'px'}document.documentElement.style.setProperty('--stage',backdrop.value);swatches.innerHTML=Object.values(colors).map(c=>`<span title="${c}" style="background:${c}"></span>`).join('')}palette.onchange=zoom.onchange=backdrop.onchange=update;toggle.onclick=()=>{paused=!paused;setPlayback()};update();setPlayback();</script></html>'''.replace("PAYLOAD",payload)


def build(output):
    briefs,palettes = load_sources()
    rendered = {}
    for name,brief in briefs["animations"].items():
        rendered[name] = ([draw_frame(name,p) for p in brief["frames"]],
                          [p["ticks"]*125 for p in brief["frames"]])
    report = validate(briefs,palettes,rendered)
    report["source_sha256"] = fingerprint()
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/"validation.json",report)
    if report["errors"]:
        raise ValueError("; ".join(report["errors"]))
    svg_data = {}
    manifest = {"format":1,"kind":"character","id":"monke-pilot","name":"Monke (pilot preview)",
                "colors":{},"fur_palettes":list(palettes["fur"].values()),"poses":{}}
    # The preview pack is built here, not installed or made the default character.
    (output/"svg").mkdir(exist_ok=True)
    (output/"hardware").mkdir(exist_ok=True)
    (output/"previews").mkdir(exist_ok=True)
    for name,(frames,durations) in rendered.items():
        folder = output/"frames"/name
        folder.mkdir(parents=True,exist_ok=True)
        svg = animated_svg(frames,durations,palettes,name)
        svg_data[name] = svg
        (output/"svg"/f"{name}.svg").write_text(svg,encoding="utf-8")
        manifest["poses"][briefs["animations"][name]["activity"]] = f"svg/{name}.svg"
        for i,frame in enumerate(frames):
            frame.save(folder/f"{i:02d}-materials.png")
            colorize(frame,palettes).save(folder/f"{i:02d}.png")
        for palette_name in palettes["fur"]:
            colored = [colorize(f,palettes,palette_name) for f in frames]
            # Opaque preview backdrop avoids GIF disposal/transparency ambiguity.
            previews = []
            for frame in colored:
                background = Image.new("RGB",frame.size,"#eee4ce")
                background.paste(frame,mask=frame.getchannel("A"))
                previews.append(background.resize((320,256),Image.Resampling.NEAREST))
            previews[0].save(output/"previews"/f"{name}-{palette_name}.gif",save_all=True,
                             append_images=previews[1:],duration=durations,loop=0,optimize=False,disposal=2)
        (output/"hardware"/f"monke_{name}.h").write_text(rgb565_export(frames,durations,palettes,name),encoding="utf-8")
    first = rendered["idle"][0][0]
    still = f'<svg xmlns="{XMLNS}" width="80" height="64" viewBox="0 0 80 64" shape-rendering="crispEdges">{paths_for_frame(first,palettes)}</svg>'
    (output/"svg/still.svg").write_text(still,encoding="utf-8")
    manifest["poses"]["still"] = "svg/still.svg"
    write_json(output/"manifest.json",manifest)
    write_json(output/"materials.json",{"indices":MATERIALS,"palettes":palettes,"timing":{
        name:{"durations_ms":durations,"anchor":[40,55]} for name,(_,durations) in rendered.items()}})
    with zipfile.ZipFile(output/"monke-pilot.zip","w",zipfile.ZIP_DEFLATED) as archive:
        archive.write(output/"manifest.json","manifest.json")
        for path in sorted((output/"svg").glob("*.svg")):
            archive.write(path,"svg/"+path.name)
    (output/"index.html").write_text(preview_html(briefs,palettes,svg_data,report),encoding="utf-8")
    contact_sheet(output,rendered,palettes)
    write_json(output/"agent-jobs.json",{
        "source_sha256":fingerprint(),"batch":"pilot-01","next_batch":"blocked_until_review",
        "jobs":[{"animation":name,"brief":brief,"author":"tools/monke/art.py",
                 "compile":"passed","automated_review":"passed","visual_review":"pending_user",
                 "review_checklist":["E identity and proportions","activity readable at 1x","contact and tail attachment",
                                     "comic timing","loop seam","all four palettes on light and dark backgrounds"],
                 "revision_policy":"until_acceptance_criteria_met"} for name,brief in briefs["animations"].items()]})
    print(f"Built {len(rendered)} animations; {sum(len(x[0]) for x in rendered.values())} frames. Checks passed.")
    print(f"Preview: {output/'index.html'}\nVisual review pending; remaining animations are gated.")
    return report


def contact_sheet(output,rendered,palettes):
    sheet = Image.new("RGB",(1100,160*len(rendered)+60),"#182327")
    draw = ImageDraw.Draw(sheet)
    draw.text((20,18),"MONKE / PILOT 01 - five animations, four fur palettes",fill="#f4e7c8")
    for row,(name,(frames,_)) in enumerate(rendered.items()):
        y = 60+row*160
        draw.text((20,y),name.upper(),fill="#f6cf35")
        indices = [0,len(frames)//3,2*len(frames)//3]
        examples = [(frames[i],"brown") for i in indices] + [(frames[0],p) for p in list(palettes["fur"])[1:]]
        for col,(frame,palette) in enumerate(examples):
            x = 20+col*180
            preview = colorize(frame,palettes,palette).resize((160,128),Image.Resampling.NEAREST)
            sheet.paste("#eee4ce",(x,y+16,x+160,y+144))
            sheet.paste(preview,(x,y+16),preview)
    sheet.save(output/"previews/contact-sheet.png")
    # Animated overview: all five, synchronized on their original durations.
    overview=[]
    for tick in range(64):
        panel=Image.new("RGB",(1000,190),"#182327")
        text=ImageDraw.Draw(panel)
        for col,(name,(frames,durations)) in enumerate(rendered.items()):
            t = tick*125 % sum(durations)
            i=0
            while t >= durations[i]:
                t-=durations[i]; i+=1
            sprite=colorize(frames[i],palettes).resize((160,128),Image.Resampling.NEAREST)
            x=col*200+20
            text.text((x,15),name.upper(),fill="#f6cf35")
            panel.paste("#eee4ce",(x,38,x+160,166))
            panel.paste(sprite,(x,38),sprite)
        overview.append(panel)
    overview[0].save(output/"previews/pilot-overview.gif",save_all=True,append_images=overview[1:],
                     duration=125,loop=0,optimize=False,disposal=2)


def write_json(path,data):
    path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["build","status","review"])
    parser.add_argument("--output",type=Path,default=DEFAULT_OUT)
    parser.add_argument("--decision",choices=["approved","changes_requested"])
    parser.add_argument("--note",help="User feedback supporting the review decision")
    args=parser.parse_args()
    if args.command=="build":
        build(args.output)
    else:
        path=args.output/"validation.json"
        if not path.exists():
            parser.error("No build exists; run build first")
        report=json.loads(path.read_text())
        report["stale"]=report["source_sha256"]!=fingerprint()
        if args.command=="review":
            if not args.decision or not args.note:
                parser.error("Review requires --decision and --note copied from explicit user feedback")
            if report["stale"] or report["automated"]!="passed":
                parser.error("Cannot review a failed or stale build")
            review={"source_sha256":report["source_sha256"],"decision":args.decision,"user_feedback":args.note}
            write_json(args.output/"review.json",review)
            print(json.dumps(review,indent=2))
            return
        review_path=args.output/"review.json"
        if review_path.exists():
            review=json.loads(review_path.read_text())
            if review["source_sha256"]==report["source_sha256"]:
                report["visual_review"]=review["decision"]
                report["next_batch"]="eligible_for_planning" if review["decision"]=="approved" else "blocked_until_review"
        print(json.dumps(report,indent=2))
        if report["stale"] or report["automated"]!="passed":
            sys.exit(1)


if __name__=="__main__":
    main()
