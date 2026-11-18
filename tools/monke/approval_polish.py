"""Polish the approval plate on the material grid. Run: python -m tools.monke.approval_polish"""
import json
from PIL import Image, ImageDraw
from .art import IDS, FUR_IDS
from .approval_revision import KEYS, OUT as INSERTS, state_svg
from .plate_approval import OUT as ORIGINAL, NEAREST, enlarged, prop
from .pipeline import load_sources, colorize

OUT = ORIGINAL.parent / "approval-v3"
PROP = (59, 39, 79, 56)


def actor(path):
    with Image.open(path) as source:
        frame = source.copy()
    frame.paste(0, PROP)
    return frame


def deposit(frame, part, xy):
    frame.paste(part, xy, part.point(lambda value: 255 if value else 0))


def reach_contact(reach, hook=False):
    # The body holds its lean during first contact. Only the free end of the tail
    # curls. Keep the arm above the rising tail, then draw the cuff across the wrist.
    body = reach.copy()
    body.paste(0, (43,36,60,42))
    body.paste(0, (41,42,60,49))
    tail = Image.new("L", reach.size)
    pen = ImageDraw.Draw(tail)
    curve = [(38,44),(43,46),(48,46),(52,44),(55,41),(57,37),(57,34)]
    for width, role in [(5,"outline"),(3,"fur.base")]:
        pen.line(curve, IDS[role], width=width, joint="curve")
    deposit(tail, body, (0,0))
    if hook:
        pen = ImageDraw.Draw(tail)
        arc = [(57,35),(55,33),(55,30),(56,28),(58,27),(59,27)]
        for width, role in [(5,"outline"),(3,"fur.base")]:
            pen.line(arc, IDS[role], width=width, joint="curve")
        pen.point((58,26), IDS["fur.highlight"])
    return tail


def eye_drawing(held, expression):
    frame = held.copy()
    # Two whites, a continuous brow and a consistent pupil size at native scale.
    # All eye pixels have fixed materials, including the space between the eyes.
    rows = {
        "side_eye": ["  ####   ### ", " #wwww# #www#", "#www### #w###",
                     "#www### #w###", "#wwwww# #www#", " #####   ### "],
        "plead":    ["  ####   ### ", " #wwww# #www#", "#ww##w# ###w#",
                     "#ww##w# ###w#", "#wwwww# #www#", " #####   ### "],
        "lid":      ["  ####   ### ", " #    # #   #", "####### #####",
                     "#ww##w# ###w#", "#wwwww# #www#", " #####   ### "],
        "blink":    ["  ####   ### ", " #    # #   #", "             ",
                     "#     # #   #", " #####   ### ", "             "],
    }[expression]
    ink = {" ":IDS["skin.base"], "#":IDS["outline"], "w":IDS["white"]}
    for y,row in enumerate(rows,15):
        for x,ch in enumerate(row,28):
            frame.putpixel((x,y),ink[ch])
    return frame


def uncoil(idea):
    body=idea.copy()
    # Clear only the rear curl up to its attachment behind the hip.
    for top,bottom,right in [(8,24,21),(24,29,14),(29,38,14),(38,42,19),(42,47,22)]:
        body.paste(0,(0,top,right,bottom))
    tail=Image.new("L",body.size)
    pen=ImageDraw.Draw(tail)
    arc=[(25,41),(21,44),(15,44),(10,42),(7,38),(7,33),(9,30),(12,29),(15,30)]
    for width,role in [(5,"outline"),(3,"fur.base")]:
        pen.line(arc,IDS[role],width=width,joint="curve")
    deposit(tail,body,(0,0))
    return tail


def build():
    OUT.mkdir(exist_ok=True)
    _, palettes = load_sources()
    poses = {key: actor(ORIGINAL/f"key-{i}-materials.png") for i,key in enumerate(KEYS,1)}
    poses["touch"] = reach_contact(poses["reach"])
    poses["hook"] = reach_contact(poses["reach"], hook=True)
    poses["recoil"] = actor(INSERTS/"recoil-materials.png")
    held = poses["plead"]
    for expression in ("plead","side_eye","lid","blink"):
        poses[expression] = eye_drawing(held,expression)
    poses["uncoil"] = uncoil(poses["idea"])
    # Ease into the yank with a half-lifted forearm. Preserve the body and feet
    # from the braced key while allowing the registered limb to rise at the shoulder.
    settle = poses["side_eye"].copy()
    arm = Image.new("L",settle.size)
    box = (44,24,69,38)
    arm.paste(settle.crop(box), box[:2])
    settle.paste(0, box)
    tilted = arm.rotate(12,NEAREST,center=(44,35))
    deposit(settle,tilted,(0,0))
    # Connect the moving cuff to the same continuous tail below the elbow.
    pen = ImageDraw.Draw(settle)
    for width,role in [(4,"outline"),(2,"fur.base")]:
        pen.line([(47,38),(48,36),(48,34)],IDS[role],width=width)
    poses["settle"] = settle
    planted = poses["reach"].crop((0,50,59,56))
    button = prop().resize((20,20),NEAREST)
    for key, frame in poses.items():
        frame.paste(planted,(0,50))
        for y in range(button.height):
            for x in range(button.width):
                assert not (button.getpixel((x,y)) and frame.getpixel((59+x,36+y))), key
        deposit(frame,button,(59,36))
    # Identical head/torso through the three contact keys. The blink changes eyes only.
    for k in ("touch","hook"):
        assert poses[k].crop((0,0,52,36)).tobytes() == poses["reach"].crop((0,0,52,36)).tobytes()
    for key in ("lid","blink","side_eye"):
        for y in range(64):
            for x in range(80):
                if not (28 <= x < 41 and 15 <= y < 21):
                    assert poses[key].getpixel((x,y)) == poses["plead"].getpixel((x,y))
    timing = {
        "intro":[["neutral",430],["idea",210],["uncoil",100],["swing",90],["reach",100],["touch",120],
                 ["hook",110],["recoil",120],["settle",90],["side_eye",140],["plead",850]],
        "waiting":[["plead",1450],["lid",60],["blink",80],["lid",70],["plead",1240]],
        "demo_reset":[["cuff",180],["swing",110],["idea",200],["neutral",320]]
    }
    (OUT/"timing.json").write_text(json.dumps(timing,indent=2)+"\n")
    (OUT/"approval.svg").write_text(state_svg(poses,timing,palettes),encoding="utf-8")
    order = timing["intro"]+timing["waiting"]+timing["demo_reset"]
    for palette in ("brown","teal"):
        rendered = []
        for key, ms in order:
            frame = poses[key]
            rgb = colorize(frame,palettes,palette)
            base = colorize(frame,palettes,"brown")
            assert all(a==b or m in FUR_IDS for a,b,m in zip(rgb.get_flattened_data(),base.get_flattened_data(),frame.get_flattened_data()))
            rendered.append(enlarged(rgb))
        rendered[0].save(OUT/f"approval-{palette}.gif",save_all=True,append_images=rendered[1:],
                         duration=[ms for _,ms in order],loop=0,disposal=2)
    keys=["reach","touch","hook","recoil","settle","side_eye","plead","blink"]
    strip=Image.new("RGB",(160*4,150*2),"#EDE4D2")
    for i,key in enumerate(keys):
        x,y=(i%4)*160,(i//4)*150
        strip.paste(enlarged(colorize(poses[key],palettes),2),(x,y))
        ImageDraw.Draw(strip).text((x+10,y+130),key.replace("_"," ").upper(),fill="#513023")
    strip.save(OUT/"contact.png")
    (OUT/"index.html").write_text(REVIEW_PAGE, encoding="utf-8")


REVIEW_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monke · Approval study</title><style>
*{box-sizing:border-box}body{max-width:760px;margin:4vh auto;padding:20px;background:#222323;
color:#f4e7c8;font:16px system-ui}h1{margin:0 0 20px;font-size:28px}section{display:flex;
align-items:flex-end;gap:24px;flex-wrap:wrap}figure{margin:0}figcaption{margin:8px 0 16px}
img{display:block;background:#ede4d2;image-rendering:pixelated;max-width:100%;height:auto}
button,a{color:#fff}button{background:#524035;border:1px solid #a58664;padding:8px 14px;
font:inherit;cursor:pointer}a{margin-left:12px}details{margin-top:24px}summary{cursor:pointer}
</style><main><h1>Monke needs approval</h1><section><figure><img class="state" src="approval.svg"
width="320" height="256" alt="Monke reaches for the red button, catches his wrist and waits">
<figcaption>4×</figcaption></figure><figure><img class="state" src="approval.svg" width="80" height="64"
alt="Actual size"><figcaption>80 × 64 pixels</figcaption></figure></section>
<button type="button" id="replay">Replay reach</button>
<a href="../approval-v2/approval-brown.gif">Previous cut</a><a href="approval-teal.gif">Teal fur</a>
<details><summary>Inspect the catch poses</summary><img src="contact.png" width="640" height="300"
alt="Reach, first contact, hook, recoil, settle, glance, plea, and blink"></details></main>
<script>document.querySelector('#replay').onclick=()=>{
const url='approval.svg?replay='+Date.now();for(const img of document.querySelectorAll('.state'))img.src=url
}</script></html>"""


if __name__=="__main__":
    build()

