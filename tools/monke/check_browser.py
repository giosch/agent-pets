"""Verify real browser playback, material isolation and the exported SVG pack.

python -m tools.monke.check_browser --browser /path/to/chrome
Requires optional playwright package; uses an existing browser, no browser download.
"""
import argparse
import base64
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

from .pipeline import DEFAULT_OUT, ROOT, load_sources, fingerprint


def check(browser_path, output):
    sys.path.insert(0,str(ROOT/"host"))
    from clawd_tank_habitat.themes import read_archive
    errors=[]
    briefs,_=load_sources()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=browser_path,headless=True)
        try:
            page=browser.new_page(viewport={"width":1180,"height":1000},device_scale_factor=1)
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto((output/"index.html").as_uri())
            assert page.locator("article").count()==5
            # Test first/middle/last instant of EVERY frame at browser CSS computed style.
            for name,brief in briefs["animations"].items():
                svg=page.locator("article").filter(has=page.locator("h2",has_text=name)).locator(".stage svg")
                boundaries=[]
                t=0
                for i,frame in enumerate(brief["frames"]):
                    duration=frame["ticks"]*125
                    boundaries.extend((t+delta,i) for delta in (1,duration/2,duration-1))
                    t+=duration
                for time,expected in boundaries:
                    visible=svg.evaluate('''(svg,t)=>{for(const a of svg.getAnimations({subtree:true})){a.pause();a.currentTime=t}return [...svg.querySelectorAll('[data-frame]')].filter(g=>Number(getComputedStyle(g).opacity)>.5).map(g=>Number(g.dataset.frame))}''',time)
                    assert visible==[expected],(name,time,expected,visible)
            # Foreground paths must preserve their values even if RGB overlaps fur.
            fixed=page.locator('[data-material]:not([data-material^="fur."])').evaluate_all('(els)=>els.map(e=>e.getAttribute("fill"))')
            page.select_option("#palette","teal")
            assert fixed==page.locator('[data-material]:not([data-material^="fur."])').evaluate_all('(els)=>els.map(e=>e.getAttribute("fill"))')
            assert page.locator('[data-material="fur.base"]').first.get_attribute("fill")=="#34787A"
            page.click("#toggle")
            card=page.locator("article").first
            card.locator("input").fill("3")
            assert card.locator("output").text_content()=="3"
            page.select_option("#zoom","1")
            assert card.locator(".stage svg").evaluate("e=>e.getBoundingClientRect().width")==80
            page.select_option("#zoom","4")
            page.select_option("#palette","brown")
            page.screenshot(path=str(output/"previews/browser-review.png"),full_page=True)
            # Test actual exported/round-tripped themed image documents, not just inline source SVGs.
            pack=read_archive(output/"monke-pilot.zip")
            for variant in range(4):
                for pose in pack.manifest["poses"]:
                    data=base64.b64encode(pack.svg(pose,variant)).decode()
                    page.set_content(f'<img width="320" height="256" src="data:image/svg+xml;base64,{data}">')
                    assert page.locator("img").evaluate("async img=>{await img.decode();return img.naturalWidth}")==80
            page.emulate_media(reduced_motion="reduce")
            page.goto((output/"index.html").as_uri())
            assert page.locator("#toggle").text_content()=="Play all"
            for svg in page.locator(".stage svg").all():
                visible=svg.evaluate("s=>[...s.querySelectorAll('[data-frame]')].filter(g=>Number(getComputedStyle(g).opacity)>.5).map(g=>g.dataset.frame)")
                assert visible==["0"],visible
            assert not errors,errors
        finally:
            browser.close()
    report={"browser":"passed","source_sha256":fingerprint(),"checks":["all frame intervals have exactly one visible frame",
            "fixed materials unaffected by fur selection","pause and frame scrub","1x logical size",
            "24 themed pack documents decode","reduced motion"],"errors":errors}
    (output/"browser-validation.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser",required=True)
    parser.add_argument("--output",type=Path,default=DEFAULT_OUT)
    args=parser.parse_args()
    check(args.browser,args.output.resolve())
