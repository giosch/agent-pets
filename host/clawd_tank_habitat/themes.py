"""Read authoring manifests and export/install self-contained SVG renderer packs."""
import io
import json
import re
import sys
from xml.etree import ElementTree
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from clawd_tank_daemon.session_store import write_json_atomic

ASSETS = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]) / "assets"
if Path(__file__).with_name("assets").is_dir():
    ASSETS = Path(__file__).with_name("assets")
SLUG = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
SWATCH = re.compile(r"#[\da-fA-F]{6}\Z")
FUR_MATERIALS = {"fur.shadow", "fur.base", "fur.highlight"}
MAX_PACK = 8 * 1024 * 1024
POSES = {
    "scene", "idle", "working", "resting", "inspecting", "editing", "executing",
    "researching", "coordinating", "external", "question", "approval", "ready", "failure",
    "completed", "setback", "compacted", "interrupted",
    "wake", "walking", "departing", "helper", "compact_work", "parallel", "coffee", "groove", "hat",
    "building", "transferring", "pushing", "thinking", "eureka", "overheated", "offline", "low_power", "still",
}


@dataclass
class Pack:
    manifest: dict
    files: dict[str, str]

    @classmethod
    def load(cls, manifest, read_asset):
        kind, name, key = (manifest.get(k) for k in ("kind", "name", "id"))
        if kind not in {"character", "habitat"} or not isinstance(key, str) or not SLUG.fullmatch(key):
            raise ValueError("Invalid pack kind or ID")
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise ValueError("A pack needs a display name")
        colors = manifest.get("colors", {})
        if not isinstance(colors, dict) or any(k not in {"body", "shadow", "accent"} or
                not isinstance(v, str) or not SWATCH.fullmatch(v) for k, v in colors.items()):
            raise ValueError("Invalid palette roles")
        fur_palettes = manifest.get("fur_palettes")
        if fur_palettes is not None:
            if (colors or not isinstance(fur_palettes, list) or not 1 <= len(fur_palettes) <= 32 or
                    any(not isinstance(p, dict) or set(p) != FUR_MATERIALS or
                        any(not isinstance(v, str) or not SWATCH.fullmatch(v) for v in p.values())
                        for p in fur_palettes)):
                raise ValueError("Fur palettes need three material colors and no legacy colors")
        poses = manifest.get("poses")
        if not isinstance(poses, dict) or ("idle" if kind == "character" else "scene") not in poses:
            raise ValueError("A character needs an idle pose and a habitat needs a scene")
        files = {}
        mapping = {}
        for pose, source in poses.items():
            if pose not in POSES or not isinstance(source, str) or not source.endswith(".svg"):
                raise ValueError("Unknown pose or artwork format")
            if source not in mapping:
                local_name = f"art-{len(mapping)}.svg"
                svg = read_asset(source)
                if len(svg) > MAX_PACK:
                    raise ValueError("Invalid SVG artwork")
                try:
                    root = ElementTree.fromstring(svg)
                except ElementTree.ParseError as error:
                    raise ValueError(f"Invalid SVG in {source}") from error
                if root.tag != "{http://www.w3.org/2000/svg}svg":
                    raise ValueError(f"Expected SVG artwork in {source}")
                if fur_palettes is not None:
                    for element in root.iter():
                        material = element.get("data-material", "")
                        if material.startswith("fur.") and material not in FUR_MATERIALS:
                            raise ValueError("Unknown fur material")
                files[local_name] = svg
                mapping[source] = local_name
        packed = {"format": 1, "kind": kind, "id": key, "name": name, "colors": colors,
                  "poses": {pose: mapping[src] for pose, src in poses.items()}}
        if fur_palettes is not None:
            packed["fur_palettes"] = fur_palettes
        return cls(packed, files)

    def svg(self, pose: str, variant: int) -> bytes:
        poses = self.manifest["poses"]
        fallback = "scene" if self.manifest["kind"] == "habitat" else "idle"
        src = self.files[poses.get(pose, poses[fallback])]
        if "fur_palettes" in self.manifest:
            # Material identity, not an RGB match: brown props/skin stay fixed.
            palette = self.manifest["fur_palettes"][variant % len(self.manifest["fur_palettes"])]
            root = ElementTree.fromstring(src)
            root.set("data-pose", pose)
            for element in root.iter():
                material = element.get("data-material")
                if material in palette:
                    element.set("fill", palette[material])
            return ElementTree.tostring(root, encoding="utf-8")
        # The same slot maintains its color even while it is off screen. Extra
        # sessions get golden-angle hues instead of cycling a short color list.
        initial = [16, 168, 271, 43, 218, 326]
        hue = initial[variant] if variant < len(initial) else (variant * 137.508) % 360
        roles = {"body": (67, 66), "shadow": (41, 43), "accent": (80, 84)}
        for role, color in self.manifest["colors"].items():
            saturation, lightness = roles[role]
            src = re.sub(re.escape(color), f"hsl({hue:.3f}, {saturation}%, {lightness}%)",
                         src, flags=re.IGNORECASE)
        src = re.sub(r"<svg(?=[\s>])", f'<svg data-pose="{pose}"', src, count=1)
        if pose == "offline":
            # The browser uses a broken-link symbol in the original board artwork.
            src = src.replace("M -3,3 L 3,-3 L 0,-6 L 0,6 L 3,3 L -3,-3",
                              "M -4,1 l 2,-2 M 1,1 l 3,-3 M -2,-4 l 1,2 M 1,3 l 1,1")
        return src.encode("utf-8")

    def archive(self, destination: Path):
        with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(self.manifest, indent=2))
            for name, contents in self.files.items():
                archive.writestr(name, contents)


def read_archive(path: Path) -> Pack:
    if path.stat().st_size > MAX_PACK:
        raise ValueError("Theme archive exceeds 8 MiB")
    try:
        with ZipFile(io.BytesIO(path.read_bytes())) as archive:
            if sum(f.file_size for f in archive.infolist()) > MAX_PACK:
                raise ValueError("Expanded theme exceeds 8 MiB")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != 1:
                raise ValueError("Unsupported theme format")
            return Pack.load(manifest, lambda name: archive.read(name).decode("utf-8"))
    except (BadZipFile, KeyError, UnicodeError) as error:
        raise ValueError("Unreadable theme archive") from error


class Themes:
    def __init__(self, installed: Path):
        self.packs: dict[tuple[str, str], Pack] = {}
        for path in sorted((ASSETS / "habitat" / "packs").glob("*.json")):
            pack = Pack.load(json.loads(path.read_text(encoding="utf-8")),
                             lambda name: (ASSETS / name).read_text(encoding="utf-8"))
            self.add(pack)
        for path in sorted(installed.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.add(Pack.load(data["manifest"], data["files"].__getitem__))

    def add(self, pack: Pack):
        self.packs[pack.manifest["kind"], pack.manifest["id"]] = pack

    def catalog(self) -> list[dict]:
        return [{**{k: p.manifest[k] for k in ("kind", "id", "name")}, "poses": list(p.manifest["poses"])}
                for p in self.packs.values()]


def install_pack(source: Path, installed: Path) -> Path:
    pack = read_archive(source)
    target = installed / f"{pack.manifest['kind']}-{pack.manifest['id']}.json"
    write_json_atomic(target, {"manifest": pack.manifest, "files": pack.files})
    return target
