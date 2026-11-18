"""Build the per-user installer on its target OS with Python and PyInstaller."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
RES = ROOT / "host/clawd_tank_habitat/install_resources"


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def compile_windows(source, output, *extra, subsystem="winexe"):
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    run(compiler, "/nologo", "/target:" + subsystem, "/optimize+", "/r:System.Windows.Forms.dll",
        "/out:" + str(output), *extra, DESKTOP/source)


def mac_sign(path):
    identity = os.environ.get("MACOS_SIGN_IDENTITY")
    if identity:
        run("codesign","--force","--timestamp","--options","runtime","--sign",identity,path)


def win_sign(path):
    cert = os.environ.get("WINDOWS_SIGN_THUMBPRINT")
    if cert:
        run("signtool","sign","/sha1",cert,"/fd","SHA256","/tr","http://timestamp.digicert.com","/td","SHA256",path)


def build(dest, version):
    dest.mkdir(parents=True,exist_ok=True)
    system = platform.system().lower()
    machine = platform.machine().lower()
    name = f"Clawd-Tank-{version}-{system}-{machine}"
    with tempfile.TemporaryDirectory(prefix="habitat-build-") as tmp:
        work = Path(tmp)
        data = [(ROOT/"assets/habitat","assets/habitat"),(ROOT/"assets/svg-animations","assets/svg-animations"),
                (ROOT/"host/clawd_tank_habitat/web","clawd_tank_habitat/web"),(RES,"clawd_tank_habitat/install_resources")]
        flags = []
        if system == "windows":
            shim = work/"clawd-tank.exe"
            compile_windows("WindowsLauncher.cs",shim,subsystem="exe")
            gui = work/"clawd-tank-desktop.exe"
            compile_windows("WindowsLauncher.cs",gui)
            for entry in (shim,gui):
                win_sign(entry)
                data.append((entry,"clawd_tank_habitat/install_resources"))
        if system == "darwin" and os.environ.get("MACOS_SIGN_IDENTITY"):
            flags.extend(["--codesign-identity",os.environ["MACOS_SIGN_IDENTITY"]])
        for src,target in data:
            flags.extend(["--add-data",str(src)+os.pathsep+target])
        run(sys.executable,"-m","PyInstaller","--noconfirm","--onedir","--name","habitat-runtime",
            "--specpath",work,"--workpath",work/"pyi","--distpath",work/"dist",*flags,ROOT/"host/habitat.py")
        app = work/"dist/habitat-runtime"
        if system == "windows" and os.environ.get("WINDOWS_SIGN_THUMBPRINT"):
            for path in app.rglob("*"):
                if path.suffix.lower() in {".dll",".pyd",".exe"}:
                    verified = subprocess.run(["signtool","verify","/pa",str(path)], capture_output=True)
                    if verified.returncode:
                        win_sign(path)
            run("signtool","verify","/pa",app / "habitat-runtime.exe")
        if system == "darwin":
            shortcut = app / "desktop-assets/Clawd Tank Habitat.app"
            binary = shortcut / "Contents/MacOS"
            binary.mkdir(parents=True)
            run("cc","-O2","-o",binary/"clawd-tank",DESKTOP/"mac-launch.c")
            (shortcut/"Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":"io.clawdtank.desktop",
                "CFBundleExecutable":"clawd-tank","CFBundleName":"Clawd Tank Habitat","CFBundlePackageType":"APPL",
                "CFBundleVersion":version,"CFBundleShortVersionString":version}))
            mac_sign(shortcut)
        files = {p.relative_to(app).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(app.rglob("*")) if p.is_file()}
        (app/"release.json").write_text(json.dumps({"version":version,"files":files},sort_keys=True), encoding="utf-8")
        if system == "windows":
            archive = work/"habitat.zip"
            with ZipFile(archive,"w",ZIP_DEFLATED) as z:
                for p in sorted(app.rglob("*")):
                    if p.is_file():
                        z.write(p,p.relative_to(app))
            target = dest/(name+"-Setup.exe")
            compile_windows("WindowsSetup.cs",target,"/r:System.IO.Compression.dll",
                            "/r:System.IO.Compression.FileSystem.dll","/resource:"+str(archive)+",habitat.zip")
            win_sign(target)
            if os.environ.get("WINDOWS_SIGN_THUMBPRINT"):
                run("signtool","verify","/pa", target)
        elif system == "darwin":
            volume = work/"volume"
            installer = volume/"Install Clawd Tank.app"
            binary = installer/"Contents/MacOS"
            binary.mkdir(parents=True)
            run("cc","-O2","-DINSTALLER","-o",binary/"install",DESKTOP/"mac-launch.c")
            (installer/"Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleName":"Install Clawd Tank",
                "CFBundleIdentifier":"io.clawdtank.installer","CFBundlePackageType":"APPL","CFBundleExecutable":"install",
                "CFBundleVersion":version,"CFBundleShortVersionString":version}))
            (installer/"Contents/Resources").mkdir()
            shutil.move(str(app),str(installer/"Contents/Resources/runtime"))
            mac_sign(installer)
            target=dest/(name+".dmg")
            run("hdiutil","create","-ov","-volname","Clawd Tank Setup","-srcfolder",volume,target)
            mac_sign(target)
            if os.environ.get("MACOS_NOTARY_PROFILE"):
                run("xcrun","notarytool","submit",target,"--keychain-profile",os.environ["MACOS_NOTARY_PROFILE"],"--wait")
                run("xcrun","stapler","staple",target)
        else:
            archive=work/"payload.tar.gz"
            with tarfile.open(archive,"w:gz") as tar:
                tar.add(app,arcname="runtime")
            target=dest/(name+".run")
            header = """#!/bin/sh
set -eu
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
tail -n +8 "$0" | tar -xz -C "$tmp"
"$tmp/runtime/habitat-runtime" desktop-install "$@"
exit 0
"""
            with target.open("wb") as f, archive.open("rb") as payload:
                f.write(header.encode())
                shutil.copyfileobj(payload,f)
            target.chmod(0o755)
        (dest/(target.name+".sha256")).write_text(hashlib.sha256(target.read_bytes()).hexdigest()+"  "+target.name+"\n")
        print(target,flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--version",default="0.1.0")
    args=parser.parse_args()
    import re
    if not re.fullmatch(r"\d+\.\d+\.\d+",args.version):
        parser.error("Use a three-part desktop release version")
    build(args.out.resolve(),args.version)
