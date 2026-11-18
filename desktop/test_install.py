"""Black-box release acceptance on a disposable OS user (GitHub hosted runners)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

def run(argv, **kwargs):
    return subprocess.run(list(map(str,argv)),check=True,timeout=150,**kwargs)


def main(first, second):
    with tempfile.TemporaryDirectory(prefix="habitat-user-") as tmp:
        home=Path(tmp)
        # Windows registry and macOS Launch Services are exercised on the disposable CI user.
        env={**os.environ,"HOME":tmp,"USERPROFILE":tmp,"LOCALAPPDATA":str(home/"local"),
             "APPDATA":str(home/"roam"),"CODEX_HOME":str(home/"codex"),"CLAUDE_CONFIG_DIR":str(home/"claude"),
             "XDG_DATA_HOME":str(home/"data"),"XDG_CONFIG_HOME":str(home/"config"),
             "CLAWD_HABITAT_HOME":str(home/"state")}
        state=home/"state"
        def install(artifact):
            if sys.platform=="win32":
                run([artifact,"/quiet","/no-launch"],env=env)
            elif sys.platform=="darwin":
                mount=home/"mount"
                mount.mkdir(exist_ok=True)
                run(["hdiutil","attach","-nobrowse","-readonly","-mountpoint",mount,artifact],env=env)
                try:
                    run([mount/"Install Clawd Tank.app/Contents/MacOS/install","--no-open"],env=env)
                finally:
                    run(["hdiutil","detach",mount],env=env)
            else:
                run(["sh",artifact,"--no-open"],env=env)
        if sys.platform=="win32":
            root=home/"local/Programs/ClawdTankHabitat"
        elif sys.platform=="darwin":
            root=home/"Library/Application Support/ClawdTankDesktop"
        else:
            root=home/"data/clawd-tank-desktop"
        stable=root/("clawd-tank.exe" if os.name=="nt" else "clawd-tank")
        def cli(*args): run([stable,*args],env=env)
        def info(): return json.loads((state/"connection.json").read_text())
        def get(path):
            with urllib.request.urlopen(f"http://127.0.0.1:{info()['port']}/"+path,timeout=5) as resp:
                return json.load(resp)
        def manage(action, **values):
            data=info()
            req=urllib.request.Request(f"http://127.0.0.1:{data['port']}/manage",
                  data=json.dumps({"action":action,**values}).encode(),
                  headers={"Content-Type":"application/json","Authorization":"Bearer "+data["management"]})
            with urllib.request.urlopen(req,timeout=12) as res:
                return json.load(res)
        def event(source,sid,name):
            profile,file=("claude","settings.json") if source=="claude" else ("codex","hooks.json")
            groups=json.loads((home/profile/file).read_text())["hooks"][name]
            h,=[h for g in groups for h in g["hooks"] if h.get("statusMessage")=="Updating Clawd Tank habitat"]
            if source=="claude":
                argv=[h["command"],*h["args"]]
            elif os.name=="nt":
                argv=["powershell.exe","-NoProfile","-NonInteractive","-Command",h["commandWindows"]]
            else:
                argv=["/bin/sh","-c",h["command"]]
            run(argv,input=json.dumps({"session_id":sid,"hook_event_name":name}).encode(),env=env,cwd=home)
        def until(fn):
            for _ in range(160):
                if fn(): return
                time.sleep(.1)
            raise AssertionError("Timed out waiting for installed app")
        original={"hooks":{"Stop":[{"hooks":[{"type":"command","command":"unrelated-hook"}]}]}}
        for profile,file in [("claude","settings.json"),("codex","hooks.json")]:
            (home/profile).mkdir()
            (home/profile/file).write_text(json.dumps(original))
        # Install the previous checkout's command shapes to exercise migration on first install.
        checkout=Path(__file__).resolve().parents[1]/"host/habitat.py"
        run([sys.executable,checkout,"install-hooks","claude"],env=env)
        install(first)
        cli("launch","--background")
        pid=info()["pid"]
        cli("launch","--background")
        assert pid==info()["pid"]
        data=get("v1/connections")
        assert data["agents"]["claude"]["state"]=="installed"
        assert data["agents"]["codex"]["state"]=="available"
        assert manage("install",source="codex")["verified"]
        assert manage("probe",source="claude")["verified"]
        assert get("v1/connections")["agents"]["claude"]["last"] is None
        manage("login",enabled=True)
        manage("finish")
        event("codex","keep","SessionStart")
        event("claude","close","SessionStart")
        before=get("v1/snapshot")["sessions"]
        assert len(before)==2
        cli("stop")
        until(lambda:not (state/"connection.json").exists())
        event("claude","close","SessionEnd")
        cli("launch","--background")
        assert get("v1/snapshot")["sessions"]==[before[0]]
        pointer=(root/"current").read_bytes()
        old_hooks=(home/"codex/hooks.json").read_bytes()
        install(second)
        assert (root/"current").read_bytes()!=pointer
        assert get("v1/snapshot")["sessions"]==[before[0]]
        assert (home/"codex/hooks.json").read_bytes()==old_hooks
        assert get("v1/connections")["login"]
        event("codex","keep","Stop")
        assert get("v1/snapshot")["sessions"][0]["attention"]=="ready"
        cli("uninstall-desktop")
        until(lambda:not stable.exists())
        for profile,file in [("claude","settings.json"),("codex","hooks.json")]:
            assert json.loads((home/profile/file).read_text())==original
        assert (state/"sessions.json").exists()
        print("Packaged install, hook migration, restart, offline close, running upgrade and uninstall passed",sys.platform)


if __name__ == "__main__":
    main(*[Path(arg).resolve() for arg in sys.argv[1:]])
