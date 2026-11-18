"""Registration, fixed materials and passing drawings on the logical pixel grid."""
from PIL import Image, ImageDraw
from collections import Counter
from .art import IDS,FUR_IDS

O=IDS["outline"]
F=IDS["fur.base"]
SK=IDS["skin.base"]


def shift(frame,dx,dy=0):
    dst=Image.new("L",frame.size)
    dst.paste(frame,(dx,dy))
    return dst


def clean(frame,allowed):
    # Chroma-key/antialias fringe has no leaf, lens or error material on bare fur.
    raw=frame.copy()
    for y in range(frame.height):
        for x in range(frame.width):
            value=raw.getpixel((x,y))
            if value in allowed or value not in (IDS["leaf"],IDS["lens"],IDS["alert"],IDS["yellow"]):
                continue
            around=[raw.getpixel((xx,yy)) for yy in range(max(0,y-1),min(frame.height,y+2))
                    for xx in range(max(0,x-1),min(frame.width,x+2)) if (xx,yy)!=(x,y)]
            frame.putpixel((x,y),O if 0 in around or O in around else max(around,key=around.count))


def fixed_metal(frame,box):
    x0,y0,x1,y1=box
    for y in range(y0,y1):
        for x in range(x0,x1):
            v=frame.getpixel((x,y))
            if v in FUR_IDS or v in (IDS["skin.shadow"],SK,IDS["skin.light"]):
                frame.putpixel((x,y),IDS["beige.shadow"] if v in FUR_IDS else IDS["beige"])


def strand(image,points):
    draw=ImageDraw.Draw(image)
    for w,ink in ((4,O),(2,F)):
        draw.line(points,fill=ink,width=w,joint="curve")


def fixed_islands(frame):
    """Keep isolated ink marks on fingers, mouths, soles and props fixed."""
    pixels=frame.load()
    pending={(x,y) for y in range(frame.height) for x in range(frame.width) if pixels[x,y] in FUR_IDS}
    while pending:
        seed=pending.pop()
        component=[seed]
        neighbors=Counter()
        for x,y in component:
            for xx,yy in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if (xx,yy) in pending:
                    pending.remove((xx,yy))
                    component.append((xx,yy))
                elif 0<=xx<80 and 0<=yy<64 and pixels[xx,yy] not in FUR_IDS:
                    neighbors[pixels[xx,yy]]+=1
        if len(component)<=15:
            surrounding=neighbors.most_common()
            material=next((m for m,n in surrounding if m not in (0,O)),O)
            if material in (SK,IDS["skin.light"]):
                material=IDS["skin.shadow"]
            for xy in component:
                pixels[xy]=material
    skins={IDS["skin.base"],IDS["skin.light"],IDS["skin.shadow"]}
    for y in range(64):
        for x in range(2,78):
            if pixels[x,y] not in FUR_IDS:
                continue
            for dx,dy in ((1,0),(0,1)):
                if y < 2 or y>=62:
                    continue
                if any(pixels[x-dx*n,y-dy*n] in skins for n in (1,2)) and any(
                    pixels[x+dx*n,y+dy*n] in skins for n in (1,2)):
                    pixels[x,y]=IDS["skin.shadow"]
                    break


def fix_region(frame,box,material):
    for y in range(box[1],box[3]):
        for x in range(box[0],box[2]):
            if frame.getpixel((x,y)) in FUR_IDS:
                frame.putpixel((x,y),material)


def keyboard(frame, top):
    # One registered perspective keyboard, with a raised lip and a coiled cord.
    frame.paste(0,(24,top,80,64))
    d=ImageDraw.Draw(frame)
    d.line([(62,top+5),(67,top+4),(69,top+6),(69,top+9),(68,top+10)],fill=O,width=2)
    d.polygon([(27,top),(59,top),(64,top+5),(64,top+9),(24,top+9),(24,top+5)],fill=IDS["beige.shadow"],outline=O)
    d.polygon([(28,top+1),(58,top+1),(62,top+5),(26,top+5)],fill=IDS["beige"])
    for row in range(2):
        for x in range(29-row,59,4):
            d.line([(x,top+2+row*2),(x+1,top+2+row*2)],fill=IDS["steel"])
    d.line([(35,top+6),(49,top+6)],fill=O)


def gait(poses):
    # Separate the two planted contact intervals by clear passing silhouettes.
    raw=poses["0"]
    palm=raw.crop((57,49,67,56))
    sole=raw.crop((13,50,23,56))
    supports=[
        ((19,55),(33,54),(43,55),(62,55)),((19,55),(36,51),(44,51),(62,55)),
        ((23,52),(37,54),(49,51),(62,55)),((27,50),(37,55),(61,55),(50,52)),
        ((30,52),(37,55),(61,55),(46,50)),((19,55),(34,52),(61,55),(43,53)),
    ]
    for i,contacts in enumerate(supports):
        frame=poses[str(i)]
        dy=[0,1,0,-1,0,0][i]
        body=frame.crop((0,0,80,39)).copy()
        canvas=Image.new("L",frame.size)
        d=ImageDraw.Draw(canvas)
        for j,((ex,ey),(hx,hy)) in enumerate(zip(contacts,[(30,37),(33,37),(43,36),(49,36)])):
            knee=(hx-3 if j<2 else hx+3,(hy+ey)//2)
            pts=[(hx,hy+dy),knee,(ex,ey-4)]
            for w,c in ((7,O),(5,IDS["fur.shadow"] if j in (1,2) else F)):
                d.line(pts,fill=c,width=w,joint="curve")
            pad=sole if j<2 else palm
            canvas.paste(pad,(ex-4,ey-pad.height+1),pad.point(lambda a:255 if a else 0))
        d.ellipse((28,32+dy,49,42+dy),fill=IDS["fur.shadow"],outline=O)
        d.ellipse((36,33+dy,48,41+dy),fill=IDS["skin.shadow"])
        canvas.paste(body,(0,dy),body.point(lambda a:255 if a else 0))
        poses[str(i)]=canvas


def polish(name, poses):
    if name in ("idle","still","resting","editing","ready","question","failure","low_power"):
        allowed={"failure":{IDS["alert"]},"low_power":{IDS["alert"]},"question":{IDS["yellow"]}}.get(name,set())
        for frame in poses.values():
            clean(frame,allowed)
    if name in ("idle","still","resting"):
        # Register the seat/feet, tail and palm on the near knee across all seated keys.
        base=poses["0"]
        for frame in poses.values():
            frame.paste(base.crop((0,47,80,64)),(0,47))
    if name == "idle":
        rub=poses["2"].copy()
        hand=rub.crop((43,11,53,19))
        rub.paste(0,(43,11,53,19))
        rub.paste(hand,(42,12),hand.point(lambda a:255 if a else 0))
        poses["rub"]=rub
        look=poses["0"].copy()
        head=look.crop((29,12,58,32)).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        look.paste(head,(29,12))
        look.paste(0,(56,17,59,24))
        poses["look"]=look
    if name == "editing":
        poses["left"]=poses["1"].copy()
        for frame in poses.values():
            fix_region(frame,(24,41,70,53),IDS["beige.shadow"])
            fixed_metal(frame,(27,44,68,52))
            keyboard(frame,43)
    if name == "failure":
        feet=poses["0"].crop((10,50,58,56))
        badge=poses["3"].crop((52,2,72,21))
        for i,(dx,dy) in enumerate([(0,0),(1,0),(4,0),(2,1),(3,1),(4,1)]):
            frame=shift(poses[str(i)],dx,dy)
            if i>=2:
                # Badge is a screen overlay independent of the pulling movement.
                frame.paste(0,(52,0,78,21))
                frame.paste(badge,(52,2),badge.point(lambda a:255 if a else 0))
            frame.paste(feet,(10,50))
            poses[str(i)]=frame
        held=poses["3"]
        blink=held.copy()
        d=ImageDraw.Draw(blink)
        d.rectangle((35,14,45,18),fill=SK)
        d.line([(35,16),(37,17),(39,17),(40,16)],fill=O)
        d.line([(41,16),(43,17),(45,16)],fill=O)
        poses["4"]=blink
        poses["5"]=held.copy()
        for frame in poses.values():
            fix_region(frame,(10,53,58,56),IDS["skin.shadow"])
            fix_region(frame,(52,2,72,21),IDS["alert"])
    if name == "low_power":
        base=poses["0"]
        feet=base.crop((22,51,57,56))
        post=base.crop((57,38,66,56))
        battery=base.crop((55,3,71,17))
        for i,dx in enumerate((0,3,5,9,10,10)):
            frame=poses[str(i)].copy()
            # Isolate the UI symbol before registering the cane. The final breath
            # puff stays attached to the mouth, independent of the battery.
            # Battery is its own connected component above and to the right of the face.
            frame.paste(0,(55,0,74,17))
            frame=shift(frame,dx)
            frame.paste(battery,(64,-2),battery.point(lambda a:255 if a else 0))
            frame.paste(0,(20,51,57,56))
            if i>=3:
                frame.paste(0,(0,50,28,56))
                d=ImageDraw.Draw(frame)
                points=[(35,45),(32,49),(28,51),(23,52),(19,52)]
                d.line(points,fill=O,width=5)
                d.line(points,fill=F,width=3)
            frame.paste(feet,(22,51),feet.point(lambda a:255 if a else 0))
            frame.paste(post,(57,38))
            poses[str(i)]=frame
        breath=poses["4"].copy()
        d=ImageDraw.Draw(breath)
        d.line([(70,26),(72,25),(74,26)],fill=IDS["beige"])
        d.point((76,25),fill=IDS["white"])
        poses["5"]=breath
    if name == "question":
        for i in (3,4,5):
            body=poses[str(i)]
            # From the lower spine to the outside edge of the question-shaped tip.
            strand(body,[(28,41),(23,43),(16,42),(11,39),(7,33),(6,23),(7,16),(10,13)])
        hold=poses["4"].copy()
        hold.paste(poses["5"].crop((34,9,52,20)),(34,9))
        poses["5"]=hold
        for frame in poses.values():
            frame.paste(poses["0"].crop((0,45,80,64)),(0,45))
    if name == "ready":
        body=poses["0"].copy()
        for y in range(48):
            edge=32 if y<27 else 28 if y<40 else 32 if y<43 else 36
            body.paste(0,(0,y,edge,y+1))
        for i,path in enumerate((
            [],[(35,44),(27,43),(21,39),(17,34),(15,27),(16,23),(19,24),(21,27)],
            [(35,44),(27,43),(21,40),(16,33),(14,26),(15,22),(20,29),(24,30),(29,22)],
            [(35,44),(27,43),(20,40),(16,34),(13,26),(14,21),(17,21),(23,30),(25,29),(34,15)],
            [(35,44),(27,43),(20,40),(16,34),(13,26),(14,21),(17,21),(23,30),(25,29),(36,12)],
        )):
            if i:
                frame=Image.new("L",body.size)
                strand(frame,path)
                frame.paste(body,mask=body.point(lambda a:255 if a else 0))
                poses[str(i)]=frame
        blink=poses["4"].copy()
        draw=ImageDraw.Draw(blink)
        draw.rectangle((44,17,50,18),fill=SK)
        draw.line([(45,18),(48,18),(50,17)],fill=O)
        poses["5"]=blink
    if name == "walking":
        gait(poses)
    if name in ("interrupted","compact_work"):
        top=45 if name=="interrupted" else 44
        grounded=poses["0"].crop((0,48,24,64))
        for frame in poses.values():
            if name=="interrupted":
                # Clear the former keyboard under the hovering fingertips.
                frame.paste(0,(24,43,80,64))
                frame.paste(grounded,(0,48))
            keyboard(frame,top)
            clean(frame,set())
        if name=="interrupted":
            for x in (34,50):
                d=ImageDraw.Draw(poses["0"])
                d.polygon([(x-2,40),(x+1,40),(x+1,44),(x,46),(x-2,46),(x-2,43)],fill=SK,outline=O)
                d.line((x-1,40,x,40),fill=SK)
            for key in ("1","2","3"):
                raw=poses[key]
                held=Image.new("L",raw.size)
                draw=ImageDraw.Draw(held)
                # One planted leg carries the pelvis as the shoulders lift.
                draw.polygon([(16,51),(17,45),(18,40),(23,36),(31,35),(40,38),(42,42),(38,46),(31,47),(27,51),(24,53)],fill=F,outline=O)
                draw.ellipse((28,31,42,44),fill=SK,outline=O)
                upper=raw.crop((0,0,80,40))
                held.paste(upper,(0,0),upper.point(lambda a:255 if a else 0))
                if key in ("1","2"):
                    # Extend the curled fingers to their original tips without
                    # copying any part of the old keyboard below the hand.
                    d=ImageDraw.Draw(held)
                    x=54 if key=="1" else 50
                    d.polygon([(x-2,37),(x+1,37),(x+2,39),(x+1,42),(x,42),(x-1,40),(x-2,40)],fill=SK,outline=O)
                held.paste(grounded,(0,48),grounded.point(lambda a:255 if a else 0))
                keyboard(held,top)
                if key=="1":
                    d=ImageDraw.Draw(held)
                    d.polygon([(35,41),(38,41),(38,44),(37,46),(35,46)],fill=SK,outline=O)
                    d.line((35,41,37,41),fill=SK)
                poses[key]=held
            held=poses["3"]
            blink=held.copy()
            draw=ImageDraw.Draw(blink)
            draw.rectangle((36,14,46,18),fill=SK)
            draw.line([(36,16),(39,17),(40,16)],fill=O)
            draw.line([(42,16),(44,17),(46,16)],fill=O)
            poses["4"]=blink
        else:
            # Give the other index finger a separate lift between the short taps.
            lift=poses["0"].copy()
            draw=ImageDraw.Draw(lift)
            draw.polygon([(27,38),(35,35),(40,37),(40,42),(36,43),(29,43),(27,42)],fill=IDS["skin.shadow"],outline=O)
            draw.polygon([(27,37),(29,35),(34,34),(37,35),(37,36),(39,36),(39,38),(35,38),(34,39),(29,39)],fill=SK,outline=O)
            draw.point((32,37),fill=IDS["skin.shadow"])
            poses["lift"]=lift
    if name == "departing":
        clock=poses["0"].crop((53,33,73,56))
        fixed_metal(clock,(0,0,clock.width,clock.height))
        # Save the moving layers before introducing the stationary timeclock.
        runner=poses["5"].copy()
        leaf=poses["0"].crop((50,18,60,29))
        for i in range(6):
            frame=poses[str(i)]
            if i in (3,4): frame.paste(0,(52,29,80,64))
            if i<3: frame.paste(0,(51,34,80,64))
            if i in (2,3,4,5):
                # Tuck the punched timecard behind the clock, leaving its green tip visible.
                if i==2:
                    frame.paste(0,(48,18,62,30))
                    draw=ImageDraw.Draw(frame)
                    draw.ellipse((47,28,53,32),fill=SK,outline=O)
            if i>=4:
                frame=shift(frame,(i-3)*6,1)
                poses[str(i)]=frame
            if i>=2:
                frame.paste(leaf,(56,28),leaf.point(lambda a:255 if a else 0))
            frame.paste(clock,(53,33),clock.point(lambda a:255 if a else 0))
        runner=shift(runner,35,1)
        runner.paste(leaf,(56,28),leaf.point(lambda a:255 if a else 0))
        runner.paste(clock,(53,33),clock.point(lambda a:255 if a else 0))
        poses["out"]=runner
        end=Image.new("L",(80,64))
        end.paste(leaf,(56,28),leaf.point(lambda a:255 if a else 0))
        end.paste(clock,(53,33))
        poses["end"]=end
    if name in ("idle","still","resting","editing","ready","question","failure","low_power","walking","departing","interrupted","compact_work"):
        for frame in poses.values():
            fixed_islands(frame)

