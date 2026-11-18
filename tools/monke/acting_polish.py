"""Material-grid cleanup and performance keys for the six character acting plates."""
from collections import Counter

from PIL import Image, ImageDraw

from .art import FUR_IDS, IDS
from .production_polish import shift


O = IDS["outline"]
F = IDS["fur.base"]
S = IDS["skin.base"]
D = IDS["skin.shadow"]
CREAM = IDS["beige"]
TAN = IDS["beige.shadow"]
IRON = IDS["steel"]
Y = IDS["yellow"]
GOLD = IDS["yellow.shadow"]
WHITE = IDS["white"]
GREEN = IDS["leaf"]
RED = IDS["alert"]
WOOD = IDS["prop.wood"]
SKIN = {S, D, IDS["skin.light"]}
SIGNAL = {GREEN, RED, IDS["lens"], Y, GOLD}


def overlay(target, source, position=(0, 0)):
    target.paste(source, position, source.point(lambda value: 255 if value else 0))


def protect(im, box, replacement=D):
    """A fixed painted surface may share the brown coat's RGB on the source plate."""
    x0, y0, x1, y1 = box
    for x in range(x0, x1):
        for y in range(y0, y1):
            if im.getpixel((x, y)) in FUR_IDS:
                im.putpixel((x, y), replacement)


def material_cleanup(frame, name):
    # Keep a connected coat shape, but reject brown marks enclosed by skin,
    # a prop or the background. Work from a snapshot so runs are deterministic.
    original = frame.copy()
    pixels = original.load()
    remaining = {(x, y) for y in range(64) for x in range(80) if pixels[x, y] in FUR_IDS}
    while remaining:
        seed = remaining.pop()
        group = [seed]
        for x, y in group:
            for q in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if q in remaining:
                    remaining.remove(q)
                    group.append(q)
        if len(group) <= 9:
            for x, y in group:
                near = original.crop((x-1, y-1, x+2, y+2)).get_flattened_data()
                frame.putpixel((x, y), D if any(v in SKIN for v in near) else O)
    for y in range(1, 63):
        for x in range(1, 79):
            value = pixels[x, y]
            if value == 0:
                continue
            neighbors = [pixels[i, j] for i in range(x-1, x+2)
                         for j in range(y-1, y+2) if (i, j) != (x, y)]
            if value in FUR_IDS:
                if sum(v in SKIN for v in neighbors) >= 5:
                    frame.putpixel((x, y), D)
            elif value in (IRON,TAN,CREAM) and name in ("completed","setback","coffee","hat"):
                # Bare skin and coat carry no gray hardware reflections.
                ink=D if any(v in SKIN for v in neighbors) else O if 0 in neighbors else F
                frame.putpixel((x,y),ink)
            elif value in SIGNAL:
                if value in (Y, GOLD) and (name in ("coffee", "setback") or name=="hat" and y<18):
                    continue
                sample = [v for v in neighbors if v and v not in SIGNAL]
                frame.putpixel((x, y), O if 0 in neighbors else
                               Counter(sample).most_common(1)[0][0] if sample else O)


def registered(poses, offsets):
    for i, (dx, dy) in enumerate(offsets):
        poses[str(i)] = shift(poses[str(i)], dx, dy)


def completed(poses):
    # Register the weight-bearing foot before and after the jump, and both
    # shoes through the bow. The passing bow compresses the torso at the hips.
    registered(poses, [(0,-3), (0,-2), (4,-3), (-1,-3), (3,-3), (1,-3)])
    poses["rise"] = shift(poses["0"], 0, -2)
    poses["drop"] = shift(poses["1"], 1, 2)
    for i in ("0","2","3","4","5"):
        protect(poses[i], (15,52,58,57))
    held = poses["3"].crop((16,51,58,57))
    for i in ("4","5"):
        poses[i].paste(held, (16,51))
    # Open the bowed silhouette at the hip. Translating complete scanlines
    # keeps the tail's single-pixel ink and the hip-to-thigh contact intact.
    folded = poses["4"]
    incline = folded.copy()
    incline.paste(0,(0,0,80,45))
    for y in range(45):
        source_y = 45 - round((45-y)*0.90)
        dx = -round((45-y)*0.14)
        incline.paste(folded.crop((0,source_y,80,source_y+1)),(dx,y))
    poses["incline"] = incline


def desk_layer():
    layer = Image.new("L", (80,64))
    d = ImageDraw.Draw(layer)
    d.rectangle((52,43,70,54), fill=WOOD, outline=O)
    d.rectangle((54,47,68,53), fill=D)
    d.line((56,49,59,49), fill=WOOD)
    d.line((64,51,66,51), fill=WOOD)
    d.rectangle((50,41,72,45), fill=TAN, outline=O)
    d.polygon([(53,40),(55,36),(69,36),(70,40)], fill=CREAM, outline=O)
    for x in range(56,69,3):
        d.point((x,38), fill=IRON)
    d.line((56,40,64,40), fill=IRON)
    return layer


def peel(layer, x):
    d = ImageDraw.Draw(layer)
    d.polygon([(x-5,54),(x-3,52),(x-1,52),(x,49),(x+2,49),(x+2,51),
               (x+5,52),(x+6,54),(x+2,53),(x,52),(x-1,54)], fill=Y, outline=O)
    d.line((x,51,x-2,53), fill=GOLD)


def setback(poses):
    # Isolate the moving character from the fixed set before registration.
    cutoffs = [49,49,50,50,50,49]
    lower = [38,38,37,41,39,38]
    shifts = [(0,0),(1,0),(1,0),(1,2),(1,3),(1,3)]
    for i in range(6):
        f = poses[str(i)]
        f.paste(0,(cutoffs[i],0,80,64))
        f.paste(0,(lower[i],48,80,64))
        if i>=4:
            f.paste(0,(39,37,80,64))
        if i == 4:
            f.paste(0,(39,15,51,43))  # recovery puff, separate from the desk
        body = shift(f,*shifts[i])
        protect(body,(9,51,44,58))
        layer = desk_layer()
        peel(layer, [43,36,41,45,46,46][i])
        overlay(layer,body)
        poses[str(i)] = layer
    # The peel travels with the front sole before slipping away. Delay the
    # final grounded pose until the rear hand releases the floor.
    falling = poses["2"].copy()
    body = falling.crop((3,10,49,49))
    falling.paste(0,(3,10,49,49))
    overlay(falling,body,(4,13))
    poses["fall"]=falling
    rest=poses["5"]
    d=ImageDraw.Draw(rest)
    d.line([(46,33),(50,33),(54,35),(56,36)],fill=O,width=4)
    d.line([(46,33),(50,33),(54,35),(56,36)],fill=S,width=2)
    key = rest.copy()
    d=ImageDraw.Draw(key)
    d.line([(51,34),(55,36),(57,38)],fill=O,width=4)
    d.line([(51,34),(55,36),(57,38)],fill=S,width=2)
    poses["key"]=key


def helper(poses):
    # Plates 2–5 show the wrench rising from belt to shoulder. Its gray
    # surfaces stay fixed. The grounded side of each step shares a baseline.
    registered(poses, [(0,0),(0,0),(2,5),(-1,10),(2,10),(0,10)])
    for i in ("2","3","4","5"):
        f = poses[i]
        protect(f,(18,52,55,57))
    base = poses["5"]
    for key, foot in (("step",(21,49,36,56)),("other",(36,49,51,56))):
        pose = base.copy()
        crop = pose.crop(foot)
        pose.paste(0,foot)
        overlay(pose,crop,(foot[0]+1,foot[1]-2))
        poses[key]=pose
    dip=base.copy()
    dip.paste(0,(0,0,80,50))
    overlay(dip,base.crop((0,0,80,49)),(0,1))
    poses["dip"]=dip


def banana(draw, points):
    draw.polygon(points,fill=Y,outline=O)
    draw.line(points[1:4],fill=GOLD)


def coffee(poses):
    registered(poses,[(0,0),(1,0),(1,0),(0,3),(1,3),(2,3)])
    for i in range(6):
        protect(poses[str(i)],(18,51,55,57))
    for key, lifted in (("pick",False),("raise",True)):
        pose=poses["0"].copy()
        pose.paste(0,(54,38,75,58))
        d=ImageDraw.Draw(pose)
        wrist=(56,35) if lifted else (58,46)
        elbow=(51,40) if lifted else (53,44)
        for width,ink in ((6,O),(4,F)):
            d.line([(45,34),elbow,wrist],fill=ink,width=width)
        x,y=wrist
        banana(d,[(x-2,y+2),(x+2,y+3),(x+6,y),(x+7,y-6),
                  (x+6,y-8),(x+5,y-3),(x+1,y),(x-2,y)])
        d.ellipse((x-2,y-2,x+2,y+2),fill=S,outline=O)
        poses[key]=pose
    # Lift the entire fruit and holding hand into mouth contact, then lower the
    # shortened exposed fruit. The unpeeled phone does not reappear on the loop.
    bite=poses["5"].copy()
    fruit=bite.crop((43,27,62,45))
    bite.paste(0,(44,27,64,45))
    overlay(bite,fruit,(40,23))
    pose=poses["5"]
    d=ImageDraw.Draw(pose)
    d.rectangle((48,26,56,30),fill=0)
    d.line([(49,31),(50,30),(51,31),(53,30),(55,31)],fill=O)
    d.line((50,32,54,32),fill=WHITE)
    chew=pose.copy()
    d=ImageDraw.Draw(chew)
    d.line((39,28,43,28),fill=S)
    d.line((40,29,43,29),fill=O)
    poses["bite"]=bite
    poses["chew"]=chew


def coconut(layer, flex):
    d=ImageDraw.Draw(layer)
    d.ellipse((50,33,72,55),fill=WOOD,outline=O)
    d.ellipse((52,35,67,50),fill=D)
    d.arc((51,34,70,53),200,270,fill=CREAM,width=2)
    d.line((65,36,68,38),fill=WHITE,width=2)
    # A tiny reflected face and bent arm occupy the warm side of the shell.
    d.ellipse((55,39,61,44),fill=WOOD)
    d.rectangle((57,41,62,43),fill=S)
    d.point((60,41),fill=O)
    d.line([(56,45),(59,45),(60,48)],fill=WOOD,width=2)
    if flex:
        d.line([(60,46),(63,45),(63,42)],fill=WOOD,width=2)
        d.point((63,42),fill=S)
    d.arc((52,34,71,54),5,95,fill=O)
    d.line((53,35,58,33),fill=O)
    d.line((66,34,69,36),fill=O)
    d.line((51,43,52,39),fill=O)
    d.point((66,49),fill=O)
    d.point((68,48),fill=O)
    d.point((68,51),fill=O)


def hat(poses):
    dxs=[0,-1,2,1,1,1]
    for i,dx in enumerate(dxs):
        f=poses[str(i)]
        f.paste(0,(49,31,80,64))
        body=shift(f,dx,0 if i<3 else -1)
        protect(body,(15,51,49,57))
        coconut(body,i>=3)
        poses[str(i)]=body


def television(layer, lost, crack=False):
    d=ImageDraw.Draw(layer)
    d.rectangle((54,48,56,52),fill=WOOD,outline=O)
    d.rectangle((68,48,70,52),fill=WOOD,outline=O)
    d.line([(56,16),(61,20),(65,15)],fill=O)
    d.rounded_rectangle((50,20,74,49),radius=3,fill=D,outline=O)
    d.rounded_rectangle((52,23,68,45),radius=2,fill=O)
    d.rectangle((53,24,67,44),fill=GREEN)
    if lost:
        d.line((55,27,65,39),fill=RED,width=3)
        d.line((65,27,55,39),fill=RED,width=3)
    else:
        d.line((54,38,57,38),fill=CREAM,width=2)
        d.rectangle((62,29,63,30),fill=Y)
    if crack:
        d.line([(61,29),(59,32),(61,34),(58,37)],fill=O)
        d.line([(60,33),(64,33),(66,31)],fill=O)
    d.ellipse((70,25,72,27),fill=CREAM,outline=O)
    d.line((71,33,72,33),fill=IRON)
    d.line((71,35,72,35),fill=IRON)


def pad(layer,x,y,tilt=0):
    d=ImageDraw.Draw(layer)
    points=[(0,2),(2,0),(5,1),(8,0),(10,2),(11,5),(10,6),
            (7,4),(4,4),(1,6),(0,5)]
    d.polygon([(x+a,y+b+tilt*(a//4)) for a,b in points],fill=CREAM,outline=O)
    d.point((x+3,y+2),fill=O)
    d.point((x+8,y+2+tilt*2),fill=RED)


def groove(poses):
    # Keep the TV planted through the release and separate the controller
    # from both the hand and the screen for an actual airborne exposure.
    limits=[47,46,46,44,46,44]
    for i,x in enumerate(limits):
        f=poses[str(i)]
        f.paste(0,(x,0,80,64))
        if i>=3:
            f.paste(0,(41,16,48,25))
        protect(f,(8,46,23,55),IRON)
        protect(f,(24,49,45,54),D)
        # Cup and headband sit inside the tail silhouette and remain steel.
        cup_x=[21,21,20,19,19,19][i]
        protect(f,(cup_x-2,20,cup_x+4,27),IRON)
        if i in (0,1):
            protect(f,(28,31,43,42),D)
        television(f,i>=2,i>=4)
    lost=poses["1"].copy()
    television(lost,True)
    poses["lost"]=lost
    flying=poses["3"].copy()
    pad(poses["2"],13,20,-1)
    pad(poses["3"],36,24,-1)
    pad(flying,45,24,-1)
    poses["flying"]=flying
    pad(poses["4"],55,28,1)
    bounce=poses["4"].copy()
    television(bounce,True,True)
    pad(bounce,48,40,1)
    poses["bounce"]=bounce
    pad(poses["5"],43,50,0)


def polish(name, poses):
    functions={"completed":completed,"setback":setback,"helper":helper,
               "coffee":coffee,"hat":hat,"groove":groove}
    for frame in poses.values():
        material_cleanup(frame,name)
    functions[name](poses)
