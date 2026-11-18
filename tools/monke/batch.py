"""Verify or audit every generated plate without granting visual approval."""
import argparse
import json
from pathlib import Path
from .production import BASE, CUTS, ROOT, save_json
from .plate_review import packet, read, verify, decision


def receipt(directory, name):
    path=directory/"review"/(name+".json")
    return read(path) if path.exists() else {}


def run(command,browser=None,names=None):
    queue=[line.split("|")[1].strip() for line in (ROOT/"assets/monke/source/production-queue.md").read_text().splitlines()
           if line.startswith("| ") and not line.startswith("| Pack pose")]
    statuses={}
    for name in queue:
        if names and name not in names:
            continue
        directory=ROOT/"assets/monke/plate-study/approval-v3" if name=="approval" else CUTS/name
        if not (directory/"candidate.json").exists():
            statuses[name]="awaiting_artwork"
            continue
        _,_,digest=packet(directory)
        tech=receipt(directory,"technical")
        if command=="verify" and (tech.get("candidate")!=digest or tech.get("result")!="pass"):
            save_json(directory/"review/technical.json",{"candidate":digest,"result":"pending"})
            tech=verify(directory,browser)
            save_json(directory/"review/technical.json",tech)
        statuses[name]=decision(digest,tech,{r:receipt(directory,r) for r in ("art","motion")})
        print(name, statuses[name], digest[:12],flush=True)
    if not names:
        save_json(BASE/"status.json",statuses)
    return statuses


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=("verify","audit"))
    parser.add_argument("poses",nargs="*")
    parser.add_argument("--browser")
    args=parser.parse_args()
    run(args.command,args.browser,args.poses)

