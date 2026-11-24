"""Bake browser SVG packs into native RGB565 animation data for the ES3C35P.

Requires Pillow and Playwright. Chromium is used only while exporting assets.
Run from the repository root with --browser pointing to Chrome or Chromium.
"""
import argparse
from array import array
import io
import json
import math
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
from agent_pets_habitat.themes import Themes, read_archive

SIZE = 128
KEYS = (0xF81E, 0xF81D, 0xF81C)
MARKERS = ("#FF0000", "#00FF00", "#0000FF")


def pixels(png, roles):
    result = array("H")
    for r, g, b, alpha in Image.open(io.BytesIO(png)).convert("RGBA").getdata():
        if alpha < 96:
            result.append(0xF81F)
        elif roles and max(r, g, b) > 160 and sorted((r, g, b))[1] < 65:
            result.append(KEYS[(r, g, b).index(max(r, g, b))])
        else:
            color = (r >> 3) << 11 | (g >> 2) << 5 | b >> 3
            result.append(0xF800 if color in (*KEYS, 0xF81F) else color)
    return result


def rle(values):
    result = array("B")
    previous, count = values[0], 0
    for value in values:
        if value == previous and count < 255:
            count += 1
        else:
            result.extend((previous & 255, previous >> 8, count))
            previous, count = value, 1
    result.extend((previous & 255, previous >> 8, count))
    return result


def source(pack, pose):
    svg = pack.files[pack.manifest["poses"].get(pose, pack.manifest["poses"]["idle"])]
    root = ET.fromstring(svg)
    root.set("data-pose", pose)
    root.set("width", str(SIZE))
    root.set("height", str(SIZE))
    if "fur_palettes" in pack.manifest:
        mapping = dict(zip(("fur.base", "fur.shadow", "fur.highlight"), MARKERS))
        for element in root.iter():
            if element.get("data-material") in mapping:
                element.set("fill", mapping[element.get("data-material")])
        svg = ET.tostring(root, encoding="unicode")
    else:
        svg = ET.tostring(root, encoding="unicode")
        for role, marker in zip(("body", "shadow", "accent"), MARKERS):
            color = pack.manifest.get("colors", {}).get(role)
            if color:
                svg = re.sub(re.escape(color), marker, svg, flags=re.I)
    # XML namespace prefixes break CSS tag selectors and Chromium SVG animation discovery.
    svg = svg.replace("ns0:", "").replace(":ns0", "")
    return svg


def export(browser_path, destination):
    themes = Themes(Path(".debug/no-installed-packs"))
    monke = ROOT / "assets/monke/production/monke.zip"
    if monke.exists():
        themes.add(read_archive(monke))
    words = array("B")
    refs, animations, characters, backgrounds, icons = [], [], [], [], []
    cache = {}

    def store(frame):
        key = frame.tobytes()
        if key not in cache:
            cache[key] = len(words)
            words.extend(rle(frame))
        return cache[key]

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=browser_path, headless=True)
        page = browser.new_page(viewport={"width": SIZE, "height": SIZE}, device_scale_factor=1)
        for (kind, name), pack in themes.packs.items():
            if kind != "character":
                continue
            characters.append((name, pack.manifest["name"], pack.manifest.get("fur_palettes", [])))
            poses = list(pack.manifest["poses"])
            for pose in ("working", "resting", "editing", "executing", "inspecting", "researching",
                         "coordinating", "external", "question", "approval", "failure", "ready", "completed",
                         "setback", "interrupted", "compacted", "offline", "building", "transferring"):
                if pose not in poses:
                    poses.append(pose)
            for pose in poses:
                svg = source(pack, pose)
                # Fixed CSS viewport reproduces the browser's object-fit: contain box.
                page.set_content('<style>html,body{margin:0;background:transparent}svg{display:block}</style>' + svg)
                duration = page.evaluate("""() => {
                  let end = 0;
                  for (const a of document.getAnimations()) {
                    a.pause(); const t = a.effect.getTiming();
                    end = Math.max(end, Number(t.duration) + Number(t.delay));
                  }
                  for (const s of document.querySelectorAll('svg')) s.pauseAnimations?.();
                  return end || 125;
                }""")
                intro = 0
                for element in ET.fromstring(svg).iter():
                    if element.tag.rsplit('}', 1)[-1] in {'animate', 'animateTransform'}:
                        def milliseconds(value):
                            match = re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s)', value)
                            return float(match[1]) * (1 if match[2] == 'ms' else 1000) if match else 0
                        begin = milliseconds(element.get('begin', '0ms'))
                        duration = max(duration, begin + milliseconds(element.get('dur', '0ms')))
                        if element.get('repeatCount') == 'indefinite':
                            intro = max(intro, begin)
                count = max(1, math.ceil(min(duration, 32000) / 125))
                first = len(refs)
                for frame in range(count):
                    page.evaluate("""t => {
                      for (const a of document.getAnimations()) {a.pause(); a.currentTime = t;}
                      for (const s of document.querySelectorAll('svg')) s.setCurrentTime?.(t / 1000);
                    }""", frame * duration / count)
                    png = page.screenshot(omit_background=True, animations="allow")
                    refs.append(store(pixels(png, True)))
                animations.append((len(characters) - 1, pose, first, count, round(duration), round(intro)))
                print(f"{name}/{pose}: {count} frames, {len(words) // 1024} KiB", flush=True)
        page.set_viewport_size({"width": 480, "height": 280})
        for (kind, name), pack in themes.packs.items():
            if kind == "habitat":
                svg = pack.svg("scene", 0).decode()
                page.set_content('<style>html,body{margin:0}svg{width:480px;height:280px;display:block}</style>' + svg)
                backgrounds.append((name, pack.manifest["name"], store(pixels(page.screenshot(), False))))
        page.set_viewport_size({"width": 16, "height": 16})
        index = (ROOT / "host/agent_pets_habitat/web/index.html").read_text(encoding="utf-8")
        for name, body in re.findall(r'<symbol id="s-([^"]+)"[^>]*>(.*?)</symbol>', index):
            page.set_content('<style>body{margin:0;color:#35463d}svg{width:16px;height:16px;fill:currentColor}</style>'
                             + '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">' + body + '</svg>')
            icons.append((name, store(pixels(page.screenshot(omit_background=True), False))))
        browser.close()
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        output.write('// Generated by tools/export_device_art.py from the browser packs.\n#pragma once\n#include <stdint.h>\n')
        output.write('struct DeviceAnimation {uint8_t character; const char* pose; uint32_t first; uint16_t count; uint32_t period; uint32_t intro;};\n')
        output.write('struct DeviceBackdrop {const char* id; const char* name; uint32_t offset;};\n')
        output.write('struct DeviceCharacter {const char* id; const char* name; uint8_t palettes; uint16_t colors[4][3];};\n')
        output.write('static const uint8_t artData[] = {\n')
        for i in range(0, len(words), 16):
            output.write(','.join(hex(v) for v in words[i:i+16]) + ',\n')
        output.write('};\nstatic const uint32_t artFrames[] = {\n')
        for i in range(0, len(refs), 16):
            output.write(','.join(map(str, refs[i:i+16])) + ',\n')
        output.write('};\nstatic const DeviceAnimation artAnimations[] = {\n')
        for character, pose, first, count, period, intro in animations:
            output.write(f'{{{character},"{pose}",{first},{count},{period},{intro}}},\n')
        output.write('};\nstatic const DeviceCharacter artCharacters[] = {\n')
        for name, label, palettes in characters:
            colors = []
            for palette in palettes:
                row = []
                for role in ("fur.base", "fur.shadow", "fur.highlight"):
                    rgb = int(palette[role][1:], 16)
                    row.append(((rgb >> 19) << 11) | (((rgb >> 10) & 63) << 5) | ((rgb >> 3) & 31))
                colors.append('{' + ','.join(map(str, row)) + '}')
            output.write(f'{{"{name}","{label}",{len(palettes)},{{' + ','.join(colors or ['{0,0,0}']) + '}},\n')
        output.write('};\nstatic const DeviceBackdrop artBackdrops[] = {\n')
        for name, label, offset in backgrounds:
            output.write(f'{{"{name}","{label}",{offset}}},\n')
        output.write('};\n')
        for name, offset in icons:
            output.write(f'static const uint32_t icon_{name} = {offset};\n')
    print(f"Exported {len(words)} animation bytes to {destination}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "firmware/AgentPets_ES3C35P/device_art.h")
    args = parser.parse_args()
    export(args.browser, args.output)
