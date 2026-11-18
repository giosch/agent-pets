"""Integer-grid, semantic-material artwork. No RGB matching or resampling.

All coordinates are logical pixels. Every drawable writes a MATERIAL INDEX;
the exact same frame is colored independently for browser and hardware exports.
"""
from PIL import Image, ImageDraw

MATERIALS = ["transparent", "outline", "fur.shadow", "fur.base", "fur.highlight",
             "skin.shadow", "skin.base", "skin.light", "beige", "beige.shadow",
             "steel", "yellow", "yellow.shadow", "leaf", "alert", "lens", "white", "prop.wood"]
IDS = {name: i for i, name in enumerate(MATERIALS)}
FUR_IDS = {IDS[x] for x in ("fur.shadow", "fur.base", "fur.highlight")}


class Canvas:
    def __init__(self):
        self.image = Image.new("L", (80, 64))
        self.draw = ImageDraw.Draw(self.image)

    def polygon(self, points, material, outline=True):
        self.draw.polygon(points, fill=IDS[material], outline=IDS["outline"] if outline else None)

    def rect(self, box, material, outline=False):
        self.draw.rectangle(box, fill=IDS[material], outline=IDS["outline"] if outline else None)

    def ellipse(self, box, material, outline=True):
        self.draw.ellipse(box, fill=IDS[material], outline=IDS["outline"] if outline else None)

    def line(self, points, material, width=1):
        self.draw.line(points, fill=IDS[material], width=width, joint="curve")

    def limb(self, points, material="fur.base", width=5):
        self.line(points, "outline", width + 2)
        self.line(points, material, width)


def head(c, x, y, look=0, blink=False, plead=False, smug=False):
    """Shared 16px head, including ears and projecting manager muzzle."""
    c.ellipse((x, y + 4, x + 7, y + 12), "skin.shadow")
    c.rect((x + 2, y + 7, x + 3, y + 9), "skin.base")
    c.polygon([(x+6,y+2),(x+10,y),(x+19,y),(x+21,y+2),(x+21,y+7),
               (x+25,y+8),(x+26,y+11),(x+25,y+14),(x+10,y+15),
               (x+6,y+12)], "fur.base")
    c.polygon([(x+9,y+3),(x+19,y+3),(x+21,y+7),(x+24,y+8),
               (x+25,y+12),(x+23,y+14),(x+10,y+14),(x+7,y+11),(x+7,y+6)], "skin.base", False)
    c.rect((x+10,y+3,x+18,y+4), "skin.light")
    if plead and not blink:
        c.ellipse((x+10,y+4,x+15,y+9), "white")
        c.ellipse((x+17,y+4,x+22,y+9), "white")
        c.rect((x+12,y+6,x+13,y+8), "outline")
        c.rect((x+19,y+6,x+20,y+8), "outline")
    else:
        # The heavy, flat brow is a defining E feature, never a smiling baby face.
        c.rect((x+9,y+4,x+20,y+5), "outline")
        for eye in (11, 18):
            c.rect((x+eye+look,y+6,x+eye+look+1,y+(6 if blink else 7)), "outline")
    c.line([(x+13,y+11),(x+24,y+11-(1 if smug else 0))], "outline")


def torso(c, x, y, proud=False):
    c.polygon([(x+5,y),(x+16,y),(x+21,y+5),(x+24,y+14),
               (x+22,y+19),(x+2,y+19),(x,y+14),(x+1,y+6)], "fur.base")
    c.polygon([(x+1,y+8),(x+4,y+5),(x+4,y+16),(x+7,y+18),
               (x+3,y+18),(x+1,y+15)], "fur.shadow", False)
    c.ellipse((x+7,y+3-(1 if proud else 0),x+20,y+18), "skin.shadow", False)
    c.ellipse((x+8,y+3-(1 if proud else 0),x+19,y+16), "skin.base", False)
    c.rect((x+10,y+4,x+15,y+5), "skin.light")
    c.line([(x+5,y+2),(x+8,y+1)], "fur.highlight")


def foot(c, x, y):
    c.polygon([(x+1,y),(x+6,y),(x+6,y+3),(x+11,y+3),
               (x+12,y+5),(x,y+5),(x,y+2)], "skin.base")
    c.line([(x+3,y+4),(x+3,y+4)], "skin.shadow")
    c.line([(x+7,y+4),(x+7,y+4)], "skin.shadow")


def hand(c, x, y, pointing=False):
    c.rect((x,y,x+5,y+5), "skin.base", True)
    c.rect((x+1,y+1,x+3,y+1), "skin.light")
    if pointing:
        c.rect((x+3,y+2,x+9,y+4), "skin.base", True)


def tail(c, kind="curl", shift=0):
    paths = {
        "curl": [(30,42),(23,44),(17,40),(15,33),(15,15),(17,11),(21,10),(24,12),(24,16),(21,18)],
        "check": [(30,42),(23,43),(17,38),(14,30),(14,19),(19,23),(28,11)],
    }
    c.limb([(x+shift,y) for x,y in paths[kind]], width=3)
    # Small directional highlight; main tail remains fur material throughout.
    c.line([(15+shift,22),(15+shift,30)], "fur.highlight")


def keyboard(c, pressed=-1):
    c.polygon([(24,49),(57,49),(61,56),(21,56)], "beige.shadow")
    c.polygon([(25,50),(56,50),(58,54),(23,54)], "beige", False)
    for row in range(2):
        for col in range(8):
            x,y = 26+col*4,50+row*2
            c.rect((x,y,x+2,y), "steel" if col == pressed else "beige.shadow")
    c.rect((35,54,47,54), "beige.shadow")
    c.line([(61,54),(65,54),(66,52),(65,50)], "outline")
    # A brown repair patch intentionally shares default fur base RGB. It must NOT recolor.
    c.rect((24,55,27,55), "prop.wood")


def button(c):
    c.rect((59,44,76,55), "outline")
    c.rect((60,45,75,54), "beige.shadow")
    c.rect((60,45,74,48), "beige")
    c.rect((63,50,71,52), "yellow")
    for x in (64,68):
        c.line([(x,52),(x+2,50)], "outline")
    c.ellipse((61,36,74,47), "outline", False)
    c.rect((62,42,73,46), "alert")
    c.ellipse((62,36,73,44), "alert", False)
    c.line([(64,38),(68,37),(70,37)], "white")
    c.line([(63,46),(72,46)], "outline")


def draw_frame(animation, params):
    c = Canvas()
    look = params.get("look", 0)
    if animation == "walking":
        stride = params.get("stride",0)
        dx = (0,1,2,1,0,-1,-2,-1)[stride]
        bob = (0,0,1,1,0,0,1,1)[stride]
        c.limb([(29,40),(22,40),(16,34),(14,23),(16,15),(21,14),(23,17),(21,20)], width=3)
        # Rear leg and rear planted knuckles precede torso for depth.
        c.limb([(38,42),(32-dx,48),(29-dx,50)], "fur.shadow", 5)
        foot(c,25-dx,50)
        c.limb([(41,32+bob),(48-dx,40),(48-dx,49)], "fur.shadow",5)
        hand(c,46-dx,50)
        torso(c,29,25+bob)
        head(c,35,12+bob,smug=True)
        c.limb([(43,43),(43+dx,49),(40+dx,50)],width=5)
        foot(c,37+dx,50)
        c.limb([(48,30+bob),(56+dx,39),(58+dx,49)],width=5)
        hand(c,56+dx,50)
    elif animation == "coding":
        key = params.get("key",0)
        tail(c)
        foot(c,27,50)
        foot(c,46,50)
        torso(c,29,28)
        head(c,31,13,smug=params.get("smug",False))
        keyboard(c,pressed=key+1)
        left_down = key in (1,2)
        right_down = key in (0,3)
        for x,down in ((32,left_down),(48,right_down)):
            hy = 45 if down else 40
            c.limb([(x,33),(x-3,37),(x,hy)],width=5)
            hand(c,x-2,hy)
            c.rect((x+1,hy+4,x+2,hy+5),"skin.base",True)
            if down:
                c.line([(x+5,44),(x+6,42)],"outline")
    else:
        is_approval = animation == "approval"
        x = 23 if is_approval else 30
        if not is_approval:
            tail(c, "check" if animation == "ready" else "curl")
        else:
            # Rear section joins lower back and travels under the extended arm.
            c.limb([(x+2,43),(16,43),(12,37),(12,25),(15,20),(19,21),(20,24)],width=3)
        # Fixed 48px standing construction: head 8..23, torso 24..43, legs 44..55.
        for lx in (x+4,x+16):
            c.rect((lx,42,lx+5,51), "fur.base", True)
            foot(c,lx-2,50)
        torso(c,x,24,params.get("proud",False))
        head(c,x,8,look,params.get("blink",False),params.get("plead",False),animation=="ready")
        # Left arm: long enough for knuckles to fall near the feet.
        c.limb([(x+2,29),(x-3,37),(x-2,47)],width=5)
        hand(c,x-4,46)
        if is_approval:
            reach = params.get("reach",0)
            wrist_x = 48+reach*2
            c.limb([(x+21,28),(x+25,31),(wrist_x,31)],width=5)
            hand(c,wrist_x-1,29,True)
            # Tip wraps wrist in front. It never goes into the button's hitbox.
            c.limb([(16,43),(25,47),(41,46),(49,40),(wrist_x,32),
                    (wrist_x-2,27),(wrist_x+2,25),(wrist_x+5,28),(wrist_x+4,33)],width=3)
            button(c)
            if params.get("plead"):
                c.line([(52,13),(55,11),(57,12),(57,14),(55,16)],"outline")
                c.rect((55,19,55,19),"outline")
        elif params.get("scratch"):
            sy = params["scratch"]-1
            c.limb([(x+20,29),(x+27,21),(x+18,10+sy)],width=5)
            hand(c,x+15,8+sy)
            c.line([(x+24,8),(x+26,6)],"outline")
        else:
            # Manager hand on hip, elbows out; B-like confidence without a new torso.
            c.limb([(x+21,29),(x+28,34),(x+20,39)],width=5)
            hand(c,x+18,37)
    return c.image
