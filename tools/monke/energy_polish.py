"""Final keys, contact registration and in-between drawings for the energy plates."""
from math import cos, pi, sin
from PIL import Image, ImageDraw, ImageFilter

from .art import IDS, FUR_IDS
from .production_polish import clean, shift

O = IDS["outline"]
F = IDS["fur.base"]
S = IDS["skin.base"]
P = IDS["beige"]
M = IDS["steel"]
Y = IDS["yellow"]
G = IDS["leaf"]


def overlay(dst, src, at=(0, 0)):
    dst.paste(src, at, src.point(lambda p: 255 if p else 0))


def empty():
    return Image.new("L", (80, 64))


def hardware(im, box):
    """Keep painted metals and plastics out of the character's fur palette."""
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        for x in range(x0, x1):
            value = im.getpixel((x, y))
            if value in FUR_IDS:
                im.putpixel((x, y), M)
            elif value in (S, IDS["skin.shadow"], IDS["skin.light"]):
                im.putpixel((x, y), P)


def skin_shading(im):
    """Recover warm shadow pixels enclosed by skin on the sampled plate."""
    original=im.copy()
    skin={IDS["skin.shadow"], S, IDS["skin.light"]}
    for y in range(1,63):
        for x in range(1,79):
            if original.getpixel((x,y)) not in FUR_IDS:
                continue
            neighbors=[original.getpixel((x+dx,y+dy)) for dx,dy in
                       ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1))]
            if sum(v in skin for v in neighbors)>=4 or (
                    sum(v in skin for v in neighbors)>=2 and not any(v in FUR_IDS for v in neighbors)):
                im.putpixel((x,y),IDS["skin.shadow"])


def push(poses):
    originals = {k: v.copy() for k, v in poses.items()}
    # Hold the wheel's axle in a bearing. Rotating teeth and a painted rim mark
    # travel together; the hand-drawn fingertips overlap the wheel at contact.
    def wheel(angle):
        im = empty()
        d = ImageDraw.Draw(im)
        d.polygon([(53,33),(60,33),(60,51),(64,52),(65,55),(48,55),(48,52),(53,51)], fill=M, outline=O)
        d.line((55,37,55,50),fill=P)
        cx, cy = 57, 33
        teeth = []
        for i in range(8):
            for t, radius in ((-.5,13),(-.29,13),(-.24,16),(.24,16),(.29,13)):
                a = angle + (i + t)*pi/4
                teeth.append((round(cx + cos(a)*radius), round(cy + sin(a)*radius)))
        d.polygon(teeth, fill=IDS["beige.shadow"], outline=O)
        for i in range(8):
            a = angle + i*pi/4
            x,y = round(cx+10*cos(a)), round(cy+10*sin(a))
            d.line((x,y,round(cx+12*cos(a)),round(cy+12*sin(a))), fill=M, width=2)
        d.ellipse((51,27,63,39),fill=M,outline=O)
        d.ellipse((54,30,60,36),fill=P,outline=O)
        d.point((56,32),fill=IDS["white"])
        return im

    def body(i):
        src = originals[str(i)]
        im = src.copy()
        # Keep character-colored components and their outlines where skin and
        # wheel touch. The area left of the contact is unoccluded artwork.
        seed = src.point(lambda v: 255 if v in (2,3,4,5,6,7) else 0)
        contact = seed.filter(ImageFilter.MaxFilter(3))
        for y in range(64):
            for x in range(40,80):
                v = src.getpixel((x,y))
                if x > 48 or y > 49 or (v not in (2,3,4,5,6,7) and not (v == O and contact.getpixel((x,y)))):
                    im.putpixel((x,y),0)
        dx,dy = ((0,0),(0,0),(0,0),(-1,2),(1,2),(1,2))[i]
        im = shift(im,dx,dy)
        return im

    for key,i,angle in [('0',0,0),('reach',1,0),('1',1,0),('2',2,.11),('3',3,.29),
                        ('4',4,.57),('5',5,pi/4),('recover',3,pi/4)]:
        fig = body(i)
        fig.paste(body(1).crop((6,47,42,56)),(6,47))
        scene = wheel(angle)
        overlay(scene,fig)
        poses[key] = scene


def think(poses):
    # Walk eight small steps between turnarounds. Draw the legs beneath the
    # cap/torso plate so a foot stays in world coordinates until its heel lifts.
    standing = poses["0"].copy()
    standing.paste(0,(0,46,80,64))
    for side in ('r','l'):
        for i in range(9):
            body = shift(standing, -11 + 3*i, int(i%2 == 1))
            center = 27+3*i
            d = ImageDraw.Draw(body)
            # Local ankle offsets cancel three pixels of body travel per key
            # during contact. The passing foot lifts before the next landing.
            pairs = [((-4,54),(4,54)),((-2,50),(1,54)),((6,51),(-2,54)),
                     ((7,54),(-5,54)),((4,54),(-8,54)),((1,54),(-3,50)),
                     ((-2,54),(6,51)),((-5,54),(7,54)),((-8,54),(4,54))][i]
            for leg,(offset,yy) in enumerate(pairs):
                hip = center + (-4 if leg == 0 else 3)
                foot = center + offset
                chain=[(hip,44),(hip+(foot-hip)//2,49),(foot,yy-1)]
                d.line(chain,fill=O,width=6,joint="curve")
                d.line(chain,fill=F,width=4,joint="curve")
                d.polygon([(foot-3,yy-1),(foot+1,yy-2),(foot+5,yy),(foot+5,yy+2),(foot-3,yy+2)],fill=S,outline=O)
            if side=='l':
                body=body.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            poses[side+str(i)]=body


def idea(poses):
    # The last two keys sit slightly low in the source panel. Keep the
    # landing on the opening floor line while preserving the airborne hop.
    poses["3"]=shift(poses["3"],0,-1)
    poses["5"]=shift(poses["5"],0,-1)
    for key,im in poses.items():
        im.paste(0,(0,56,80,64))
        # The bulb, banana, and rays are fixed-color props.
        for y in range(0,18):
            for x in range(18,67):
                v=im.getpixel((x,y))
                if v in FUR_IDS or v in (S, IDS["skin.shadow"], IDS["skin.light"]):
                    im.putpixel((x,y),IDS["yellow.shadow"] if key in ("3","4","5") else M)
    dim=poses["1"].copy()
    dim.paste(poses["0"].crop((33,2,56,18)),(33,2))
    poses["dim"]=dim
    blink=poses["5"].copy()
    d=ImageDraw.Draw(blink)
    d.line([(37,25),(39,26),(40,25)],fill=O)
    d.line([(42,25),(44,25),(45,24)],fill=O)
    poses["blink"]=blink


def hot(poses):
    # Translate the full second row onto the same bench as the first row.
    for key in ('3','4','5'):
        poses[key] = shift(poses[key],0,4)
    for key,im in poses.items():
        hardware(im,(24,47,70,56))
    # The same keyboard face below the line of fingertip contact in every key.
    base=poses["0"]
    board=base.crop((23,48,69,56))
    for im in poses.values():
        im.paste(board,(23,48))
    # An unhurried point and a clear contact in the repeated aftermath.
    held=poses["5"]
    d=ImageDraw.Draw(held)
    d.line((52,42,52,44),fill=S)
    d.point((52,45),fill=O)


def disconnect(poses):
    # Green belongs to the leafy cables and red/blue to the connector tips.
    # Preserve the two ends in the same hands during the look and blink.
    for im in poses.values():
        for y in range(64):
            for x in range(80):
                if y < 29 and im.getpixel((x,y)) in (IDS["lens"],G):
                    im.putpixel((x,y),O)
    # Start with the wider, actually separated connector drawing. The far
    # forearm forms an arch above the two tips so their gap remains air.
    original_body=poses["0"]
    spread=empty()
    overlay(spread,original_body.crop((9,5,54,26)),(9,5))
    for x0,x1 in ((20,36),(40,56)):
        foot=original_body.crop((x0,51,x1,56))
        foot=foot.point(lambda v: IDS["skin.shadow"] if v in (G,IDS["lens"]) else v)
        overlay(spread,foot,(x0,51))
    # Reconstruct the intact waist first. The two grips sit ahead of this
    # contour, so approaching connectors never punch a hole through the belly.
    mid=ImageDraw.Draw(spread)
    tail=[(17,24),(17,30),(16,36),(18,40),(23,43),(30,43)]
    mid.line(tail,fill=O,width=5,joint="curve")
    mid.line(tail,fill=F,width=3,joint="curve")
    mid.polygon([(28,39),(38,39),(37,45),(32,51),(25,51),(27,45)],fill=F,outline=O)
    mid.polygon([(40,39),(48,39),(48,46),(46,51),(40,51),(41,45)],fill=F,outline=O)
    mid.polygon([(32,24),(41,24),(46,27),(48,31),(49,35),(48,39),
                 (46,42),(42,45),(34,45),(29,43),(26,39),(26,33),(28,28)],
                fill=F,outline=O)
    mid.polygon([(37,27),(43,27),(46,29),(48,33),(48,36),(47,39),
                 (44,42),(41,44),(36,44),(33,42),(32,39),(33,33)],
                fill=S,outline=O)

    def vine(draw,points,leaf):
        draw.line(points,fill=O,width=3,joint="curve")
        draw.line(points,fill=G,width=1,joint="curve")
        x,y=leaf
        draw.polygon([(x,y),(x+2,y-3),(x+5,y-3),(x+4,y),(x+1,y+1)],fill=G,outline=O)

    def separated(face, offset):
        whole=spread.copy()
        whole.paste(face.crop((21,3,54,26)),(21,3))
        arm=ImageDraw.Draw(whole)
        socket=58+offset
        # The farther shoulder reaches above both disconnected ends.
        path=[(43,27),(49,26),(54,25),(socket+2,27),(socket+7,31)]
        arm.line(path,fill=O,width=5,joint="curve")
        arm.line(path,fill=F,width=3,joint="curve")
        vine(arm,[(socket+8,36),(socket+8,40),(socket+5,43),(socket+2,44),(socket,43)],(socket+5,43))
        vine(arm,[(47,37),(46,40),(42,43),(38,44),(36,43)],(40,44))
        arm.polygon([(socket+5,29),(socket+9,29),(socket+11,31),(socket+11,35),
                     (socket+9,37),(socket+6,37),(socket+4,35),(socket+4,31)],
                    fill=S,outline=O)
        arm.line((socket+8,33,socket+8,35),fill=IDS["skin.shadow"])
        arm.rectangle((socket,31,socket+5,36),fill=IDS["lens"],outline=O)
        arm.line((socket+1,32,socket+1,35),fill=IDS["white"])
        path=[(32,29),(29,33),(29,36),(32,38),(37,38),(43,35)]
        arm.line(path,fill=O,width=7,joint="curve")
        arm.line(path,fill=F,width=5,joint="curve")
        arm.polygon([(39,33),(42,31),(45,31),(48,33),(48,36),(45,38),
                     (42,38),(39,36)],fill=S,outline=O)
        arm.line((44,35,44,37),fill=IDS["skin.shadow"])
        arm.rectangle((47,32,51,36),fill=IDS["alert"],outline=O)
        arm.line((52,32,54,32),fill=M)
        arm.line((52,36,54,36),fill=M)
        return whole
    original={k:v.copy() for k,v in poses.items()}
    poses["0"]=separated(original["0"],6)
    poses["1"]=separated(original["1"],3)
    poses["1"].paste(0,(53,6,54,10))
    poses["2"]=separated(original["2"],1)
    base=poses["2"]
    sign=poses["3"]
    held=base.copy()
    held.paste(sign.crop((7,5,54,26)),(7,5))
    # The plate's old wire glint edged into its face crop.
    held.paste(0,(52,21,55,25))
    # Long attached tail becomes one Wi-Fi arc. Supporting arcs, dot and slash
    # complete the no-signal sign. Draw the same tail into the waist.
    d=ImageDraw.Draw(held)
    d.rectangle((4,3,26,24),fill=0)
    for width,color in ((3,O),(1,F)):
        d.line([(17,27),(15,24),(11,22),(8,19),(6,15),(8,12),
                (12,9),(16,8),(20,8),(24,10),(26,12)],fill=color,width=width)
    d.line([(10,17),(13,14),(17,13),(20,13),(24,16)],fill=O,width=2)
    d.line([(14,20),(17,18),(20,18),(22,20)],fill=O,width=2)
    d.rectangle((17,22,18,23),fill=O)
    d.line((10,24,26,6),fill=O,width=3)
    d.line((10,24,26,6),fill=IDS["alert"],width=1)
    poses["3"]=held
    turn=base.copy()
    turn.paste(held.crop((28,6,55,26)),(28,6))
    poses["turn"]=turn
    blink=held.copy()
    d=ImageDraw.Draw(blink)
    d.rectangle((36,14,46,16),fill=S)
    d.line([(36,15),(38,16),(40,15)],fill=O)
    d.line([(42,15),(44,16),(46,15)],fill=O)
    poses["blink"]=blink


def swing(poses):
    # Position the holding hand along an arc under a stationary off-screen
    # vine anchor. Keep the illustrated vine below the hand and hang fresh
    # stem and leaves above it. A single prop remains behind after release.
    raw={k: v.copy() for k,v in poses.items()}
    anchor=(37,-10)
    def line(im,end,leaves=True):
        d=ImageDraw.Draw(im)
        d.line([anchor,end],fill=O,width=3)
        d.line([anchor,end],fill=G,width=1)
        if leaves:
            x=round((anchor[0]+2*end[0])/3)
            y=round((anchor[1]+2*end[1])/3)
            d.polygon([(x,y),(x-5,y-3),(x-7,y-1),(x-4,y+1)],fill=G,outline=O)
    for key,i,dx,dy,hand in [('entry',0,-54,-12,(50,17)),('arc',0,-42,-8,(50,17)),
                             ('0',0,-28,-3,(50,17)),('1',1,-15,-3,(53,24)),('2',2,-4,-2,(53,29))]:
        fig=raw[str(i)].copy()
        # Remove the original stem above the holding hand.
        hx,hy=hand
        fig.paste(0,(hx-8,0,67,hy-3))
        scene=empty()
        line(scene,(hx+dx,hy+dy))
        overlay(scene,shift(fig,dx,dy))
        poses[key]=scene
    for key,i,dx,dy,end in [('3',3,5,-4,(42,27)),('4',4,5,0,(27,23)),('5',5,6,0,(12,19))]:
        scene=empty()
        line(scene,end)
        overlay(scene,shift(raw[str(i)],dx,dy))
        poses[key]=scene


PERFORMANCE = {"pushing":push,"thinking":think,"eureka":idea,"overheated":hot,"offline":disconnect,"wake":swing}


def polish(name,poses):
    if name not in PERFORMANCE:
        return
    allowed={"thinking":{Y}, "eureka":{Y}, "offline":{G,IDS["alert"],IDS["lens"]}, "wake":{G}}
    for im in poses.values():
        clean(im,allowed.get(name,set()))
        skin_shading(im)
    if name=="thinking":
        for im in poses.values():
            hardware(im,(17,2,63,23))
    PERFORMANCE[name](poses)
