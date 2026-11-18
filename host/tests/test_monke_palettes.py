"""Material recoloring contract and backward-compatible pack round trips."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree as ET

from clawd_tank_habitat.themes import Pack, read_archive


class MonkePaletteTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"kind":"character","id":"test-monke","name":"Test Monke","colors":{},
            "poses":{"idle":"idle.svg"}, "fur_palettes":[
                {"fur.shadow":"#513023","fur.base":"#80482D","fur.highlight":"#AC7045"},
                {"fur.shadow":"#204749","fur.base":"#34787A","fur.highlight":"#63A49D"}]}
        self.svg = ('<svg xmlns="http://www.w3.org/2000/svg"><style>@keyframes a{0%{opacity:0}100%{opacity:1}}</style>'
                    '<path id="fur" data-material="fur.base" fill="#80482D" d="M0 0h1v1h-1z"/>'
                    '<path id="wood" data-material="prop.wood" fill="#80482D" d="M1 0h1v1h-1z"/>'
                    '<path id="skin" fill="#E9B47B" d="M2 0h1v1h-1z"/></svg>')

    def pack(self):
        return Pack.load(self.manifest, lambda _: self.svg)

    def test_only_fur_changes_even_with_identical_prop_rgb(self):
        root=ET.fromstring(self.pack().svg("idle",1))
        nodes={n.get("id"):n for n in root if n.get("id")}
        self.assertEqual(nodes["fur"].get("fill"),"#34787A")
        self.assertEqual(nodes["wood"].get("fill"),"#80482D")
        self.assertEqual(nodes["skin"].get("fill"),"#E9B47B")
        self.assertIn("@keyframes",ET.tostring(root).decode())

    def test_fallback_and_palette_cycle(self):
        root=ET.fromstring(self.pack().svg("editing",3))
        self.assertEqual(root.get("data-pose"),"editing")
        self.assertEqual(next(n for n in root if n.get("id")=="fur").get("fill"),"#34787A")

    def test_archive_preserves_material_palettes(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"monke.zip"
            self.pack().archive(path)
            loaded=read_archive(path)
            self.assertEqual(loaded.svg("idle",1),self.pack().svg("idle",1))

    def test_reject_invalid_material_palettes(self):
        for value in ([],{},[{"fur.base":"#80482D"}],
                      [{"fur.shadow":"red","fur.base":"#80482D","fur.highlight":"#AC7045"}]):
            self.manifest["fur_palettes"]=value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.pack()

    def test_reject_mixed_legacy_and_material_recoloring(self):
        self.manifest["colors"]={"body":"#80482D"}
        with self.assertRaises(ValueError):
            self.pack()

    def test_reject_misspelled_fur_role(self):
        self.svg=self.svg.replace("fur.base", "fur.bsae")
        with self.assertRaises(ValueError):
            self.pack()


if __name__=="__main__":
    unittest.main()
