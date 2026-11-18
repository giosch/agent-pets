"""Animation compiler invariants, independent export decoding and review gates."""
import re
import unittest
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw

from .art import MATERIALS, IDS, draw_frame
from .pipeline import (load_sources, colorize, paths_for_frame, validate, rgb565_export,
                       PILOT)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.briefs,self.palettes=load_sources()
        self.rendered={name:([draw_frame(name,p) for p in b["frames"]],
                             [p["ticks"]*125 for p in b["frames"]])
                       for name,b in self.briefs["animations"].items()}

    def test_exact_pilot_and_loop_seams(self):
        self.assertEqual(set(self.rendered),PILOT)
        for frames,durations in self.rendered.values():
            self.assertEqual(frames[0].tobytes(),frames[-1].tobytes())
            self.assertGreater(len({f.tobytes() for f in frames}),1)

    def test_palette_changes_no_fixed_pixels_in_any_frame(self):
        for frames,_ in self.rendered.values():
            for frame in frames:
                fixed=[(i,p) for i,p in enumerate(frame.get_flattened_data())
                       if not MATERIALS[p].startswith("fur.")]
                a=list(colorize(frame,self.palettes,"brown").get_flattened_data())
                b=list(colorize(frame,self.palettes,"teal").get_flattened_data())
                self.assertTrue(any(x!=y for x,y in zip(a,b)))
                self.assertTrue(all(a[i]==b[i] for i,_ in fixed))

    def test_rgb_collision_is_not_a_material_collision(self):
        frame=draw_frame("coding",{})
        self.assertEqual(self.palettes["fixed"]["prop.wood"],self.palettes["fur"]["brown"]["fur.base"])
        wood=[i for i,v in enumerate(frame.get_flattened_data()) if v==IDS["prop.wood"]]
        self.assertTrue(wood)
        a=list(colorize(frame,self.palettes,"brown").get_flattened_data())
        b=list(colorize(frame,self.palettes,"purple").get_flattened_data())
        self.assertTrue(all(a[i]==b[i] for i in wood))

    def test_svg_row_runs_decode_to_exact_material_grid(self):
        # Decode the exported paths independently to catch coordinate/off-by-one errors.
        for frames,_ in self.rendered.values():
            for frame in frames:
                root=ET.fromstring('<svg>'+paths_for_frame(frame,self.palettes)+'</svg>')
                decoded=Image.new("L",(80,64))
                draw=ImageDraw.Draw(decoded)
                for path in root:
                    material=IDS[path.get("data-material")]
                    for x,y,length,back in re.findall(r'M(\d+),(\d+)h(\d+)v1h-(\d+)z',path.get("d")):
                        self.assertEqual(length,back)
                        draw.rectangle((int(x),int(y),int(x)+int(length)-1,int(y)),fill=material)
                self.assertEqual(frame.tobytes(),decoded.tobytes())

    def test_hardware_rle_decodes_to_same_materials(self):
        for name,(frames,durations) in self.rendered.items():
            header=rgb565_export(frames,durations,self.palettes,name)
            def values(suffix):
                return list(map(int,re.search(r'monke_'+name+'_'+suffix+r'\[\] = \{([^}]*)\}',header)[1].split(',')))
            runs,offsets=values('runs'),values('offsets')
            for i,frame in enumerate(frames):
                segment=runs[offsets[i]:offsets[i+1]]
                decoded=[]
                for count,material in zip(segment[::2],segment[1::2]):
                    decoded.extend([material]*count)
                self.assertEqual(decoded,list(frame.get_flattened_data()))
            tables=[values('palette_'+p) for p in self.palettes["fur"]]
            for index,material in enumerate(MATERIALS):
                if not material.startswith('fur.'):
                    self.assertEqual(len({t[index] for t in tables}),1)

    def test_reject_extra_animations_and_changed_button(self):
        self.briefs["animations"]["external"]={}
        report=validate(self.briefs,self.palettes,{})
        self.assertTrue(any("five pilot" in e for e in report["errors"]))
        del self.briefs["animations"]["external"]
        frames,durations=self.rendered["approval"]
        frames[1].putpixel((65,39),IDS["outline"])
        report=validate(self.briefs,self.palettes,{"approval":(frames,durations)})
        self.assertTrue(any("button region changed" in e for e in report["errors"]))


if __name__=="__main__":
    unittest.main()
