"""Build evidence for Monke plate reviews and combine two independent verdicts.

python -m tools.monke.plate_review CANDIDATE_DIRECTORY prepare
python -m tools.monke.plate_review CANDIDATE_DIRECTORY verify --browser CHROME
python -m tools.monke.plate_review CANDIDATE_DIRECTORY decide
"""
import argparse
from bisect import bisect_right
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw

from .art import FUR_IDS, MATERIALS
from .pipeline import ROOT, colorize, load_sources

ROLES = {"motion", "art"}
BACKDROP = "#EDE4D2"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def packet(directory):
    spec = read(directory / "candidate.json")
    files = {role: directory / spec[role] for role in ("svg", "brown", "teal", "timing")}
    files["reference"] = ROOT / spec["reference"]
    files["direction"] = directory / "candidate.json"
    files["palette"] = ROOT / "assets/monke/source/palettes.json"
    files["rubric"] = Path(__file__).with_name("REVIEW.md")
    files["checker"] = Path(__file__)
    digest = sha256()
    for role, path in sorted(files.items()):
        digest.update(role.encode() + sha256(path.read_bytes()).digest())
    return spec, files, digest.hexdigest()


def exposures(path, size):
    poses = []
    ends = []
    duration = 0
    with Image.open(path) as gif:
        for i in range(gif.n_frames):
            gif.seek(i)
            original = gif.convert("RGB")
            native = original.resize(size, Image.Resampling.NEAREST)
            if original.tobytes() != native.resize(original.size, Image.Resampling.NEAREST).tobytes():
                raise ValueError(f"Non-integer pixel rendering in {path.name} frame {i}")
            ms = gif.info.get("duration", 0)
            if ms <= 0:
                raise ValueError("Missing exposure duration")
            duration += ms
            poses.append(native)
            ends.append(duration)
    return poses, ends


def timeline(files, spec):
    timing = read(files["timing"])
    phases = [timing[name] for name in spec["preview_phases"]]
    return [entry for phase in phases for entry in phase]


def prepare(directory):
    spec, files, digest = packet(directory)
    out = directory / "review"
    out.mkdir(exist_ok=True)
    size = tuple(spec["tile"])
    if min(size) <= 0:
        raise ValueError("Invalid logical dimensions")
    brown, ends = exposures(files["brown"], size)
    teal, teal_ends = exposures(files["teal"], size)
    events = timeline(files, spec)
    if not events or any(type(ms) is not int or ms <= 0 for _, ms in events):
        raise ValueError("Invalid timing")
    if ends[-1] != teal_ends[-1] or ends[-1] != sum(ms for _, ms in events):
        raise ValueError("Preview timelines differ")
    col, row = size
    strip = Image.new("RGB", (max(4*col,300), (row+148)*len(events)), BACKDROP)
    pen = ImageDraw.Draw(strip)
    elapsed = 0
    for i,(pose,ms) in enumerate(events):
        frame = brown[bisect_right(ends,elapsed)]
        top = i*(row+148)
        pen.text((8,top+2),f"{i+1:02}   {elapsed} ms   +{ms} ms",fill="#261C19")
        strip.paste(frame,(8,top+20))
        large = frame.resize((2*col,2*row),Image.Resampling.NEAREST)
        strip.paste(large,(col+16,top+20))
        elapsed += ms
    strip.save(out/"exposures.png")
    result = {"candidate":digest,"state":"awaiting independent reviews","duration_ms":elapsed,
              "technical_command":"verify","reviewers":sorted(ROLES)}
    write(out/"packet.json",result)
    return result


def verify(directory, browser_path):
    """Compare actual rendered state pixels against both GIFs on every exposure."""
    from playwright.sync_api import sync_playwright
    spec,files,digest = packet(directory)
    _,palettes = load_sources()
    size = tuple(spec["tile"])
    brown,ends = exposures(files["brown"],size)
    teal,teal_ends = exposures(files["teal"],size)
    timing = read(files["timing"])
    play = [entry for phase in spec["state_phases"] for entry in timing[phase]]
    loop = timing.get(spec.get("repeat_phase"),[])
    duration = sum(ms for _,ms in play)
    loop_duration = sum(ms for _,ms in loop)
    if not play or play != timeline(files,spec)[:len(play)]:
        raise ValueError("State and preview need matching initial exposures")
    roles = {name:f"#{i:02x}0000" for i,name in enumerate(MATERIALS) if i}
    with sync_playwright() as runner:
        browser = runner.chromium.launch(executable_path=browser_path,headless=True)
        page = browser.new_page(viewport={"width":size[0],"height":size[1]},device_scale_factor=1)
        page.goto(files["svg"].resolve().as_uri())
        # SVG-as-document can autoscale in Chromium. Render at precisely 1x.
        page.evaluate("""([w,h])=>{const s=document.documentElement;s.style.width=w+'px';s.style.height=h+'px';
          s.style.background='rgb(0,0,0)';s.pauseAnimations()}""",list(size))
        page.evaluate("""roles=>document.querySelectorAll('[data-material]').forEach(p=>{
          if(!roles[p.dataset.material])throw Error('Unknown material '+p.dataset.material);
          p.setAttribute('fill',roles[p.dataset.material])})""",roles)
        def snapshot(ms):
            page.evaluate("t=>document.documentElement.setCurrentTime(t/1000)",ms)
            image = Image.open(BytesIO(page.screenshot())).convert("RGB")
            values = []
            for r,g,b in image.get_flattened_data():
                if g or b or r >= len(MATERIALS):
                    raise ValueError("Unexpected pixel outside the set of material IDs")
                values.append(r)
            mask = Image.new("L",size)
            mask.putdata(values)
            return mask
        elapsed = 0
        seen = {}
        for pose,ms in play + loop:
            mid = elapsed+ms/2
            sample = snapshot(mid)
            if pose in seen and seen[pose].tobytes()!=sample.tobytes():
                raise ValueError(f"{pose} changes on repeat")
            seen[pose]=sample
            review_time = mid if mid < duration else mid-loop_duration
            for name,frames,bounds in (("brown",brown,ends),("teal",teal,teal_ends)):
                actual = colorize(sample,palettes,name)
                expected = Image.new("RGB",size,BACKDROP)
                expected.paste(actual,mask=actual.getchannel("A"))
                if expected.tobytes()!=frames[bisect_right(bounds,review_time)].tobytes():
                    raise ValueError(f"{pose} at {mid}ms: {name} preview differs from runtime material grid")
            elapsed += ms
        for box in spec.get("locked_regions",[]):
            if len({im.crop(box).tobytes() for im in seen.values()}) != 1:
                raise ValueError(f"Locked region moves: {box}")
        if spec.get("fur_visible",True) and not any(set(im.get_flattened_data()) & FUR_IDS for im in seen.values()):
            raise ValueError("Expected recolorable fur")
        page.emulate_media(reduced_motion="reduce")
        expected = seen[spec["reduced_pose"]].tobytes()
        for ms in (0,duration/2,duration+loop_duration):
            if snapshot(ms).tobytes()!=expected:
                raise ValueError("Reduced-motion pose differs")
        browser.close()
    return {"candidate":digest,"result":"pass","poses":len(seen),"observed_state_ms":elapsed}


def decision(digest, technical, reports):
    if technical.get("candidate")!=digest or technical.get("result")!="pass":
        return "needs_technical_check"
    agents = set()
    for role in sorted(ROLES):
        review = reports.get(role,{})
        if review.get("candidate")!=digest or review.get("role")!=role:
            return "needs_review"
        if (review.get("model"), review.get("effort")) != ("gpt-6.2-astra","high"):
            return "needs_review"
        agent = review.get("agent")
        if not isinstance(agent,str) or not agent.strip() or agent in agents:
            return "needs_review"
        agents.add(agent)
        if review.get("verdict") in ("revise","uncertain"):
            return "revise"
        citations = review.get("evidence")
        if (review.get("verdict")!="pass" or review.get("blockers")!=[] or
                not isinstance(citations,list) or len(citations)<2 or
                not all(isinstance(e,dict) and isinstance(e.get("observation"),str)
                        and e["observation"].strip() and isinstance(e.get("pose"),str)
                        and e["pose"].strip() for e in citations)):
            return "needs_review"
    return "accepted_for_batch"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    parser.add_argument("command",choices=["prepare","verify","decide"])
    parser.add_argument("--browser")
    args=parser.parse_args()
    out=args.directory/"review"
    if args.command=="prepare":
        result=prepare(args.directory)
    elif args.command=="verify":
        prepare(args.directory)
        # Discard the earlier attestation before attempting a fresh verification.
        write(out/"technical.json",{"result":"pending"})
        result=verify(args.directory,args.browser)
        write(out/"technical.json",result)
    else:
        _,_,digest=packet(args.directory)
        def receipt(name):
            path=out/(name+".json")
            return read(path) if path.exists() else {}
        state=decision(digest,receipt("technical"),{r:receipt(r) for r in ROLES})
        result={"candidate":digest,"state":state}
        print(json.dumps(result,indent=2))
        return 0 if state=="accepted_for_batch" else 1
    print(json.dumps(result,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

