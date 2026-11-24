"""Stage self-contained desktop releases and activate them with an atomic pointer."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import plistlib

from .adapters import SOURCES
from .desktop import control, launch, login, integration
from .hooks import configure

MARKER = "Agent Pets desktop installation v1"
RESOURCES = Path(__file__).with_name("install_resources")


def install_root():
    if os.name == "nt":
        return (Path(os.environ["LOCALAPPDATA"]) / "Programs/AgentPetsHabitat").resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/AgentPetsDesktop"
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "agent-pets-desktop"


def launcher(root):
    return root / ("agent-pets.exe" if os.name == "nt" else "agent-pets")


def atomic(path, content, mode=None):
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if mode:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def check_payload(payload):
    manifest = json.loads((payload / "release.json").read_text(encoding="utf-8"))
    for name, digest in manifest["files"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid release path")
        path = payload / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Incomplete release file: {name}")
    return manifest


def desktop_entry(root, remove=False):
    target = launcher(root)
    if os.name == "nt":
        import winreg
        link = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Agent Pets Habitat.lnk"
        reg = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentPetsHabitat"
        if remove:
            link.unlink(missing_ok=True)
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg)
            except FileNotFoundError:
                pass
            return
        link.parent.mkdir(parents=True, exist_ok=True)
        script = ("$ErrorActionPreference='Stop'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:HABITAT_LINK);"
                  "$s.TargetPath=$env:HABITAT_ENTRY; $s.WorkingDirectory=$env:LOCALAPPDATA; $s.Save()")
        subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],
                       env={**os.environ,"HABITAT_LINK":str(link),"HABITAT_ENTRY":str(root / "agent-pets-desktop.exe")}, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        manifest = json.loads((root / "releases" / (root / "current").read_text().strip() / "release.json").read_text())
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg) as key:
            for k,v in {"DisplayName":"Agent Pets Habitat","DisplayVersion":manifest["version"],
                        "InstallLocation":str(root), "DisplayIcon":str(target),
                        "UninstallString":f'"{target}" uninstall-desktop --choose-data',
                        "QuietUninstallString":f'"{target}" uninstall-desktop'}.items():
                winreg.SetValueEx(key,k,0,winreg.REG_SZ,v)
    elif sys.platform == "darwin":
        app = Path.home() / "Applications/Agent Pets Habitat.app"
        info = app / "Contents/Info.plist"
        if app.exists() and (not info.exists() or plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") != "io.agentpets.desktop"):
            raise ValueError("An unrelated application occupies the Agent Pets shortcut")
        if remove:
            if app.exists():
                shutil.rmtree(app)
            return
        release = (root / "current").read_text().strip()
        template = root / "releases" / release / "desktop-assets" / app.name
        app.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=app.parent) as tmp:
            staged = Path(tmp) / app.name
            shutil.copytree(template, staged, symlinks=True)
            old = Path(tmp) / "previous.app"
            if app.exists():
                os.replace(app,old)
            try:
                os.replace(staged,app)
            except OSError:
                if old.exists():
                    os.replace(old,app)
                raise
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share"))
        entry = base / "applications/agent-pets-habitat.desktop"
        if remove:
            entry.unlink(missing_ok=True)
            return
        entry.parent.mkdir(parents=True, exist_ok=True)
        arg = str(target).replace("\\","\\\\").replace('"','\\"').replace("$","\\$").replace("`","\\`").replace("%","%%")
        atomic(entry, ('[Desktop Entry]\nType=Application\nName=Agent Pets Habitat\nExec="' + arg +
                       '"\nIcon=applications-graphics\nTerminal=false\nCategories=Utility;\n').encode(), 0o755)


def stop_for_upgrade(directory):
    """Authenticate the running host before stopping it. Legacy hosts lack /stop."""
    info_path = directory / "connection.json"
    if not info_path.exists():
        return False
    info = json.loads(info_path.read_text())
    if control(directory,"ping"):
        if not control(directory,"stop"):
            raise RuntimeError("The running habitat could not be stopped")
        for _ in range(100):
            if not info_path.exists():
                return True
            time.sleep(.05)
        raise RuntimeError("The running habitat is still shutting down")
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1",info["port"],timeout=1)
    try:
        conn.request("POST","/internal/activity",b"{}",{"Content-Type":"application/json",
                     "Authorization":"Bearer "+info["key"]})
        if conn.getresponse().status != 400:
            raise RuntimeError("Close the existing habitat before upgrading")
    except (ConnectionRefusedError, ConnectionResetError):
        return False
    finally:
        conn.close()
    import psutil
    from .hooks import _our_hook, config_path
    import shlex
    installed = set()
    for source in SOURCES:
        path = config_path(source)
        if path.exists():
            for groups in json.loads(path.read_text(encoding="utf-8-sig")).get("hooks",{}).values():
                for group in groups:
                    for h in group.get("hooks",[]):
                        if _our_hook(h,source):
                            argv = [h["command"],*h["args"]] if source=="claude" else shlex.split(h["command"])
                            if len(argv) == 6:
                                interpreter, script = Path(argv[0]).resolve(), Path(argv[1]).resolve()
                                installed.add((interpreter, script))
                                # Framework Python's bin/python execs the Python.app inside that version.
                                framework = interpreter.parent.parent
                                if (sys.platform == "darwin" and interpreter.parent.name == "bin"
                                        and framework.parent.parent.name == "Python.framework"):
                                    installed.add(((framework / "Resources/Python.app/Contents/MacOS/Python").resolve(), script))
    for proc in psutil.process_iter():
        try:
            args = proc.cmdline()
            if len(args)<3 or "serve" not in args[2:]:
                continue
            script = (Path(proc.cwd()) / args[1]).resolve()
            if (Path(proc.exe()).resolve(),script) not in installed:
                continue
            if not any(c.status==psutil.CONN_LISTEN and c.laddr == ("127.0.0.1",info["port"])
                       for c in proc.net_connections(kind="tcp")):
                continue
            proc.terminate()
            for _ in range(100):
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    return True
                time.sleep(.05)
            raise RuntimeError("The checkout habitat is still shutting down")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    raise RuntimeError("Close the running checkout habitat and reopen the installer")


def installed_version():
    try:
        root = install_root()
        current = (root / "current").read_text().strip()
        if len(current) != 20 or any(c not in "0123456789abcdef" for c in current):
            return None
        return json.loads((root / "releases" / current / "release.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return None


def check_updates():
    import platform
    import re
    import urllib.request
    api = "https://api.github.com/repos/giosch/agent-pets/releases"
    request = urllib.request.Request(api,headers={"Accept":"application/vnd.github+json","User-Agent":"Agent-Pets-Habitat"})
    with urllib.request.urlopen(request, timeout=8) as response:
        releases = json.load(response)
    candidates = []
    for release in releases:
        match = re.fullmatch(r"desktop-v(\d+\.\d+\.\d+)", release["tag_name"])
        if not match or release["draft"] or release["prerelease"]:
            continue
        version = match[1]
        artifact = f"Agent-Pets-{version}-{platform.system().lower()}-{platform.machine().lower()}"
        suffix = "-Setup.exe" if os.name=="nt" else ".dmg" if sys.platform=="darwin" else ".run"
        if any(a["name"]==artifact+suffix for a in release["assets"]):
            candidates.append((tuple(map(int,version.split("."))), version, artifact+suffix))
    if not candidates:
        return {"version":None}
    _, version, artifact = max(candidates)
    installed = installed_version()
    newer = not installed or tuple(map(int,version.split("."))) > tuple(map(int,installed.split(".")))
    return {"version":version, "available":newer,
            "url": f"https://github.com/giosch/agent-pets/releases/download/desktop-v{version}/{artifact}"}


def activate(payload, directory, open_window=True):
    from habitat import state_owner
    root = install_root()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".habitat-install"
    if not marker.exists() and any(root.iterdir()):
        raise ValueError(f"Installation directory is already in use: {root}")
    if marker.exists() and marker.read_text() != MARKER:
        raise ValueError("Unrecognized installation directory")
    atomic(marker, MARKER.encode())
    with state_owner(root):
        manifest = check_payload(payload)
        release_id = hashlib.sha256((payload/"release.json").read_bytes()).hexdigest()[:20]
        releases = root / "releases"
        releases.mkdir(exist_ok=True)
        release = releases / release_id
        if not release.exists():
            with tempfile.TemporaryDirectory(dir=releases, prefix="stage-") as tmp:
                staged = Path(tmp) / "app"
                shutil.copytree(payload, staged, symlinks=True)
                check_payload(staged)
                os.replace(staged, release)
        check_payload(release)
        exe = release / ("habitat-runtime.exe" if os.name == "nt" else "habitat-runtime")
        subprocess.run([str(exe),"self-test"], check=True, timeout=25)
        stable = launcher(root)
        shims = [(stable, RESOURCES / ("agent-pets.exe" if os.name == "nt" else "posix-launch"))]
        if os.name == "nt":
            shims.append((root / "agent-pets-desktop.exe", RESOURCES / "agent-pets-desktop.exe"))
        os.environ["AGENT_PETS_LAUNCHER"] = str(stable)
        sources = [s for s in SOURCES if integration(s,directory)["state"] in {"installed","repair"}]
        pointer = root / "current"
        previous = pointer.read_bytes() if pointer.exists() else None
        running = stop_for_upgrade(directory)
        try:
            for executable, shim in shims:
                if executable.exists() and executable.read_bytes() == shim.read_bytes():
                    continue
                # Windows releases the launcher's executable mapping just after its host exits.
                for attempt in range(60):
                    try:
                        atomic(executable, shim.read_bytes(), 0o755)
                        break
                    except PermissionError:
                        if attempt == 59:
                            raise
                        time.sleep(.1)
            atomic(pointer, release_id.encode())
            desktop_entry(root)
            for source in sources:
                configure(source,directory)
            if open_window or running:
                launch(directory, background=not open_window)
            if previous and previous != release_id.encode():
                atomic(root / "previous", previous)
        except Exception:
            if previous:
                atomic(pointer, previous)
                if running:
                    launch(directory, background=True)
            raise
    return manifest["version"]


def rollback(directory):
    """Switch back to a previously validated release, retaining the user profile."""
    from habitat import state_owner
    root = install_root()
    if (root / ".habitat-install").read_text() != MARKER:
        raise ValueError("Unrecognized installation directory")
    with state_owner(root):
        pointer = root / "current"
        previous = root / "previous"
        if not previous.is_file():
            raise ValueError("No earlier installed release is available")
        target = previous.read_bytes()
        active = pointer.read_bytes()
        if len(target) != 20 or any(byte not in b"0123456789abcdef" for byte in target):
            raise ValueError("Invalid previous release")
        release = root / "releases" / target.decode("ascii")
        if hashlib.sha256((release / "release.json").read_bytes()).hexdigest()[:20] != target.decode():
            raise ValueError("The previous release manifest has changed")
        check_payload(release)
        exe = release / ("habitat-runtime.exe" if os.name == "nt" else "habitat-runtime")
        subprocess.run([str(exe), "self-test"], check=True, timeout=25)
        running = stop_for_upgrade(directory)
        try:
            atomic(pointer, target)
            desktop_entry(root)
            if running:
                launch(directory, background=True)
            atomic(previous, active)
        except Exception:
            if pointer.read_bytes() == target:
                stop_for_upgrade(directory)
            atomic(pointer, active)
            desktop_entry(root)
            if running:
                launch(directory, background=True)
            raise


def uninstall_from_settings(directory, purge):
    if not getattr(sys, "frozen", False) or not installed_version():
        raise ValueError("Use the installed desktop application to uninstall")
    stable = launcher(install_root())
    args = [str(stable), "--state-dir", str(directory), "uninstall-desktop"]
    if purge:
        args.append("--purge-data")
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     cwd=tempfile.gettempdir(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def uninstall(directory, purge=False):
    root = install_root()
    if (root / ".habitat-install").read_text() != MARKER:
        raise ValueError("Unrecognized installation directory")
    for source in SOURCES:
        configure(source,directory,remove=True)
    login(directory,False)
    stop_for_upgrade(directory)
    desktop_entry(root,remove=True)
    if purge:
        for filename in ["sessions.json","connection.json","activity.sqlite3","activity.sqlite3-journal",
                         "setup-complete","host.lock","host.log"]:
            # The host removes connection.json before its Windows launcher closes
            # inherited log handles. Retry only transient file-sharing errors.
            for attempt in range(60):
                try:
                    (directory / filename).unlink(missing_ok=True)
                    break
                except PermissionError as error:
                    if getattr(error, "winerror", None) not in (32, 33) or attempt == 59:
                        raise
                    time.sleep(.1)
        packs = directory/"packs"
        if packs.is_dir():
            for pack in packs.glob("*.json"):
                pack.unlink()
    if os.name == "nt":
        # The frozen runtime and its parent launcher remain loaded until return.
        cleanup = (RESOURCES / "windows-remove.ps1").read_text(encoding="utf-8")
        subprocess.Popen(["powershell.exe","-NoProfile","-NonInteractive","-Command",cleanup],
                         cwd=tempfile.gettempdir(),creationflags=subprocess.CREATE_NO_WINDOW,
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:
        shutil.rmtree(root / "releases")
        for path in [launcher(root),root/"current",root/"previous",root/"host.lock",root/".habitat-install"]:
            path.unlink(missing_ok=True)
        if not any(root.iterdir()):
            root.rmdir()
