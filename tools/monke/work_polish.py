"""Register office props and finish the ten work performances on the native grid."""
from collections import Counter

from PIL import Image, ImageDraw

from .art import FUR_IDS, IDS


INK = IDS["outline"]
BEIGE = IDS["beige"]
SHADE = IDS["beige.shadow"]
STEEL = IDS["steel"]
GOLD = IDS["yellow"]
OCHRE = IDS["yellow.shadow"]
GREEN = IDS["leaf"]
BLUE = IDS["lens"]
WHITE = IDS["white"]
SKIN = {IDS["skin.shadow"], IDS["skin.base"], IDS["skin.light"]}
FUR = set(FUR_IDS)
PROPS = (BEIGE, SHADE, STEEL)


def fix_colors(frame, box, mapping):
    left, top, right, bottom = box
    pixels = frame.load()
    for y in range(top, bottom):
        for x in range(left, right):
            value = pixels[x, y]
            if value in mapping:
                pixels[x, y] = mapping[value]


def prop(frame, box, material=SHADE):
    fix_colors(frame, box, {value: material for value in FUR})


def lock(poses, box, source="0"):
    detail = poses[source].crop(box)
    for frame in poses.values():
        frame.paste(detail, box[:2])


def shifted(frame, dx, dy):
    result = Image.new("L", frame.size)
    result.paste(frame, (dx, dy))
    return result


def neighbors(frame, x, y, radius=1):
    return frame.crop((x-radius, y-radius, x+radius+1, y+radius+1)).get_flattened_data()


def clean_edges(frame):
    # Antialiased fringes from the source key and isolated reddish JPEG pixels
    # would otherwise become false lens marks or recolorable specks on a palm.
    src = frame.copy()
    for y in range(1, 63):
        for x in range(1, 79):
            value = src.getpixel((x, y))
            if value not in FUR | {BLUE, GREEN, IDS["alert"]}:
                continue
            counts = Counter(neighbors(src, x, y))
            if value in FUR:
                if sum(counts[v] for v in FUR) <= 2 and sum(counts[v] for v in SKIN) >= 4:
                    frame.putpixel((x,y), IDS["skin.shadow"])
            elif counts[value] <= 2 and counts[0]:
                frame.putpixel((x,y), INK)


def recolor_touching(frame, materials, mapping, radius=1):
    src = frame.copy()
    for y in range(1, 63):
        for x in range(1, 79):
            value = src.getpixel((x,y))
            if value in mapping and any(v in materials for v in neighbors(src,x,y,radius)):
                frame.putpixel((x,y), mapping[value])


def working(poses):
    # Keep each bunch in the fingers from pickup through inspection to deposit.
    # The unsorted pile sits between the ripe and green sorting areas.
    base=poses["0"].copy()
    base.paste(0,(0,44,80,64))
    base.paste(0,(48,25,80,64))
    base.paste(0,(19,34,38,45))
    d=ImageDraw.Draw(base)
    d.polygon([(21,30),(28,26),(34,27),(37,35),(35,43),(19,44),(17,41)],fill=IDS["fur.base"],outline=INK)
    d.polygon([(35,27),(41,26),(47,30),(48,41),(45,44),(35,44),(31,38)],fill=IDS["skin.base"],outline=INK)
    # Preserve the entire projecting muzzle above the foreground arms.
    original=poses["0"]
    for y,end in ((23,52),(24,52),(25,53),(26,51),(27,46)):
        for x in range(33,end):
            base.putpixel((x,y),original.getpixel((x,y)))
    d.polygon([(11,44),(66,44),(71,51),(71,55),(7,55),(7,51)],fill=SHADE,outline=INK)
    d.polygon([(12,45),(65,45),(69,51),(9,51)],fill=BEIGE)
    d.line((9,53,69,53),fill=STEEL)
    def bunch(draw,x,y,c):
        draw.polygon([(x-6,y-1),(x-3,y),(x,y),(x+3,y-2),(x+4,y-5),(x+6,y-4),(x+5,y),(x+3,y+3),(x,y+4),(x-4,y+3),(x-6,y+1)],fill=c,outline=INK)
        draw.line([(x-3,y+2),(x,y+2),(x+3,y),(x+4,y-2)],fill=OCHRE)
        draw.line([(x+4,y-4),(x+3,y-6)],fill=INK)
    path=[(39,44),(39,41),(42,34),(45,25),(48,30),(54,38),(60,44),(54,39),(43,37)]
    for variant,side,other in (("ripe",1,GREEN),("green",-1,GOLD)):
        for i,(x,y) in enumerate(path):
            x=39+(x-39)*side
            frame=base.copy(); d=ImageDraw.Draw(frame)
            bunch(d,17,46,GREEN)
            bunch(d,61,46,GOLD)
            bunch(d,40,46,other)
            # The upper hand grips the stem, so the bunch hangs below it.
            wrist=(x+3,y-6) if i<=6 else (x,y-4)
            inner=(wrist[0]-5,wrist[1]+2)
            for start,end in (((26,30),inner),((44,29),wrist)):
                elbow=((start[0]+end[0])//2-3,max(start[1],end[1])+2)
                for width,ink in ((6,INK),(4,IDS["fur.base"])):
                    d.line([start,elbow,end],fill=ink,width=width,joint="curve")
            if i<=6:
                bunch(d,x,y,GOLD if side==1 else GREEN)
            else:
                bunch(d,60 if side==1 else 18,44,GOLD if side==1 else GREEN)
            for px,py in (inner,wrist):
                d.ellipse((px-2,py-2,px+2,py+2),fill=IDS["skin.base"],outline=INK)
            poses[variant+str(i)]=frame


def inspecting(poses):
    for i, frame in enumerate(poses.values()):
        prop(frame,(53,48,70,56),SHADE)
        fix_colors(frame,(53,48,70,56),{v:BEIGE for v in SKIN})
        if i:
            fix_colors(frame,(42,11,66,41),{GREEN:BLUE})
    lock(poses,(54,49,70,56))


def executing(poses):
    for frame in poses.values():
        prop(frame,(51,47,72,56),STEEL)
        recolor_touching(frame,{IDS["alert"]},{v:IDS["alert"] for v in FUR})
    lock(poses,(52,49,72,56))
    # The stopped mechanism remains in its detent while the operator peeks.
    lock({k:poses[k] for k in ("4","5")},(44,29,72,56),"4")


def banana_stamp(frame, x, y):
    d = ImageDraw.Draw(frame)
    d.line([(x,y),(x+1,y+2),(x+4,y+2),(x+6,y+1),(x+7,y-1)],fill=OCHRE)
    d.point((x+7,y-2), fill=INK)


def building(poses):
    for i, frame in enumerate(list(poses.values())):
        if i >= 3:
            frame=shifted(frame,0,1)
            poses[str(i)]=frame
        # The hard hat and bricks use the same fixed yellow ramp. Resolve
        # rust-colored hatching inside the gold silhouette before stamping.
        recolor_touching(frame,{GOLD,OCHRE},{v:OCHRE for v in FUR},2)
        prop(frame,(52,47,71,56),OCHRE)
        if i in (4,5):
            banana_stamp(frame,54,39)
    lock(poses,(52,50,71,56))
    for frame in poses.values():
        banana_stamp(frame,56,52)
    shine=poses["5"].copy()
    d=ImageDraw.Draw(shine)
    d.line((59,31,59,35),fill=WHITE)
    d.line((57,33,61,33),fill=WHITE)
    poses["shine"]=shine


def transferring(poses):
    for i, frame in enumerate(list(poses.values())):
        if i>=3:
            frame=shifted(frame,0,4)
            poses[str(i)]=frame
        for box in ((8,44,27,56),(54,44,71,56)):
            prop(frame,box,STEEL)
        recolor_touching(frame,{GOLD},{v:OCHRE for v in FUR})
    lock(poses,(8,48,27,56))
    lock(poses,(54,48,71,56))
    # Swing an empty-handed silhouette back toward the source. Keep existing
    # inventory and both baskets on the ground behind the returning courier.
    base=poses["5"].copy()
    actor=base.crop((14,13,54,55))
    # Below the waist the baskets intersect the source rectangle.
    actor.paste(0,(0,29,13,42))
    base.paste(0,(13,11,55,40))
    base.paste(0,(27,40,54,55))
    actor=actor.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    base.paste(actor,(17,13),actor.point(lambda v:255 if v else 0))
    poses["return"]=base
    lock(poses,(8,48,27,56))
    # Restore overlapping ankles in front of the rear basket edges. All contact
    # pads remain strictly between the registered basket bases.
    for key,x,y in (("1",45,49),("3",31,49),("return",31,50)):
        draw=ImageDraw.Draw(poses[key])
        draw.polygon([(x-2,y-6),(x+2,y-6),(x+2,y),(x-2,y)],fill=IDS["fur.base"],outline=INK)
        draw.polygon([(x-2,y-1),(x+1,y-1),(x+3,y),(x+5,y+1),(x+5,y+3),(x-3,y+3),(x-3,y+1)],fill=IDS["skin.base"],outline=INK)
    pickup=poses["1"]
    draw=ImageDraw.Draw(pickup)
    draw.polygon([(45,18),(48,18),(51,20),(52,22),(51,24),(47,25),(43,25)],fill=IDS["skin.base"])
    draw.line([(46,18),(49,18),(52,20),(52,23),(50,25),(45,26)],fill=INK)
    draw.polygon([(45,27),(48,28),(51,31),(51,34),(49,37),(46,38)],fill=IDS["fur.base"])
    draw.line([(46,27),(49,28),(51,31),(51,35),(48,38),(46,38)],fill=INK)


def researching(poses):
    for frame in poses.values():
        prop(frame,(50,33,72,56),STEEL)
        prop(frame,(50,13,72,27),OCHRE)
        recolor_touching(frame,{GOLD},{v:OCHRE for v in FUR})
        # Recolorable specks in the beige paper remain fixed under all skins.
        recolor_touching(frame,{BEIGE},{v:SHADE for v in FUR})
    lock(poses,(50,34,71,56))
    lock(poses,(54,15,72,27))


def coordinating(poses):
    for frame in poses.values():
        prop(frame,(38,13,67,31),SHADE)
        prop(frame,(39,31,57,49),IDS["prop.wood"])
    lock(poses,(33,13,66,16))


def parallel(poses):
    for frame in poses.values():
        for box in ((9,32,26,51),(54,32,70,51),(26,49,55,57)):
            prop(frame,box,STEEL)
    for box in ((9,33,26,51),(54,33,70,51),(26,50,55,57)):
        lock(poses,box)


def compacted(poses):
    for i,frame in enumerate(poses.values()):
        prop(frame,(64,38,74,57),IDS["prop.wood"])
        prop(frame,(51,44,65,56))
        fix_colors(frame,(57,38,74,56),{GOLD:IDS["prop.wood"],OCHRE:IDS["prop.wood"]})
        prop(frame,(6,38,19,57),SHADE)
        # Cut the rigid source-cell edge into stepped paper corners at 1x.
        for y in range(20,56):
            left=6 + (y//3)%3
            for x in range(6,left):
                frame.putpixel((x,y),0)
        recolor_touching(frame,{BEIGE},{v:SHADE for v in FUR})
    note=poses["5"].copy()
    d=ImageDraw.Draw(note)
    d.polygon([(52,46),(58,46),(57,42),(53,41)],fill=BEIGE,outline=INK)
    d.line((54,43,56,44),fill=SHADE)
    poses["note"]=note


def draw_card(draw,x,y,answer):
    draw.rectangle((x,y,x+7,y+8),fill=BEIGE,outline=INK)
    if answer:
        draw.line([(x+1,y+4),(x+3,y+6),(x+6,y+2)],fill=GREEN,width=2)
    else:
        draw.line([(x+2,y+2),(x+4,y+1),(x+5,y+2),(x+5,y+3),(x+3,y+4),(x+3,y+5)],fill=INK)
        draw.point((x+3,y+7),fill=INK)


def draw_bucket(draw,x,y,answer):
    if answer is not None:
        draw_card(draw,x-3,y-7,answer)
    draw.polygon([(x-7,y),(x+7,y),(x+5,y+8),(x+3,y+10),(x-4,y+10),(x-6,y+7)],fill=SHADE,outline=INK)
    draw.rectangle((x-7,y,x+7,y+2),fill=STEEL,outline=INK)
    draw.line((x-4,y+4,x-3,y+7),fill=BEIGE)
    draw.point((x+2,y+5),fill=STEEL)


def external(poses):
    original={k:v.copy() for k,v in poses.items()}
    mast=Image.new("L",(80,64))
    source=original["5"]
    for box in ((44,2,74,19),(44,18,52,50),(42,50,55,58)):
        mast.paste(source.crop(box),box[:2])
    prop(mast,(42,2,74,58),STEEL)
    # Every bucket position lies on the same rope. Both rotation and payout
    # are explicit, including the slack swing toward Monke's loading hand.
    bucket=[(53,47,False),(59,33,False),(61,17,False),(61,32,True),(60,47,None),(60,47,True)]
    for i, (bx,by,answer) in enumerate(bucket):
        canvas=mast.copy()
        d=ImageDraw.Draw(canvas)
        d.line([(61,18),(bx,by)],fill=INK,width=3)
        d.line([(61,18),(bx,by)],fill=OCHRE)
        d.line([(57,18),(40,37) if i in (1,2,3) else (51,27)],fill=INK,width=3)
        d.line([(57,18),(40,37) if i in (1,2,3) else (51,27)],fill=GOLD)
        draw_bucket(d,bx,by,answer)
        raw=original[str(i)]
        # Keep the hand in front of the rope and structure. No fur pixels
        # are copied from the apparatus behind the operator.
        mask=Image.new("L",raw.size)
        a=ImageDraw.Draw(mask)
        border=[(0,18),(43,18),(43,37),(41,42),(40,50),(44,52),(44,59),(0,59)]
        if i==0:
            border=[(0,23),(45,23),(45,37),(52,38),(52,44),(46,48),(40,49),(42,59),(0,59)]
        elif i==2:
            border=[(0,19),(36,19),(36,31),(41,32),(41,40),(40,49),(45,53),(45,59),(0,59)]
        a.polygon(border,fill=255)
        for x in range(80):
            for y in range(64):
                if not raw.getpixel((x,y)):
                    mask.putpixel((x,y),0)
        canvas.paste(raw,(0,0),mask)
        if i==4:
            draw_card(d,36,26,True)
        poses[str(i)]=canvas
    handoff=poses["5"].copy()
    d=ImageDraw.Draw(handoff)
    draw_bucket(d,60,47,None)
    d.rectangle((56,39,64,46),fill=0)
    d.line((60,38,60,46),fill=OCHRE)
    draw_card(d,47,32,True)
    poses["file"]=handoff
    clap=poses["5"].copy()
    d=ImageDraw.Draw(clap)
    d.rectangle((29,31,43,40),fill=0)
    for start,finish in (((27,37),(29,33)),((32,37),(39,32))):
        d.line([start,finish],fill=INK,width=5)
        d.line([start,finish],fill=IDS["fur.base"],width=3)
        x,y=finish
        d.ellipse((x-2,y-3,x+2,y+2),fill=IDS["skin.base"],outline=INK)
    poses["clap"]=clap


FINISHERS = {f.__name__:f for f in (working,inspecting,executing,building,
    transferring,researching,coordinating,external,parallel,compacted)}


def polish(name,poses):
    if name in FINISHERS:
        for frame in poses.values():
            clean_edges(frame)
        FINISHERS[name](poses)
