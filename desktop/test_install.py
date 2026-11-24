"""Black-box release acceptance on a disposable OS user (GitHub hosted runners)."""
import json
import os
import plistlib
import shlex
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
             "AGENT_PETS_HOME":str(home/"state")}
        state=home/"state"
        def install(artifact):
            if sys.platform=="win32":
                run([artifact,"/quiet","/no-launch"],env=env)
            elif sys.platform=="darwin":
                mount=home/"mount"
                mount.mkdir(exist_ok=True)
                run(["hdiutil","attach","-nobrowse","-readonly","-mountpoint",mount,artifact],env=env)
                try:
                    run([mount/"Install Agent Pets.app/Contents/MacOS/install","--no-open"],env=env)
                finally:
                    run(["hdiutil","detach",mount],env=env)
            else:
                run(["sh",artifact,"--no-open"],env=env)
        if sys.platform=="win32":
            root=home/"local/Programs/AgentPetsHabitat"
        elif sys.platform=="darwin":
            root=home/"Library/Application Support/AgentPetsDesktop"
        else:
            root=home/"data/agent-pets-desktop"
        stable=root/("agent-pets.exe" if os.name=="nt" else "agent-pets")
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
            h,=[h for g in groups for h in g["hooks"] if h.get("statusMessage")=="Updating Agent Pets habitat"]
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
        # Exercise the real source-based host that predates the desktop installer.
        checkout=Path(__file__).resolve().parents[1]/"legacy-checkout/host/habitat.py"
        run([sys.executable,checkout,"install-hooks","both"],env=env)
        with subprocess.Popen([sys.executable,checkout,"serve"],env=env) as legacy:
            try:
                until(lambda:(state/"connection.json").exists())
                event("claude","migrating","SessionStart")
                event("codex","other-migrating","SessionStart")
                original_scene=get("v1/snapshot")["sessions"]
                assert len(original_scene)==2
                install(first)
                assert legacy.poll() is not None
            finally:
                if legacy.poll() is None:
                    legacy.terminate()
        assert get("v1/snapshot")["sessions"]==original_scene
        cli("launch","--background")
        pid=info()["pid"]
        cli("launch","--background")
        assert pid==info()["pid"]
        data=get("v1/connections")
        assert data["agents"]["claude"]["state"]=="installed", (data["agents"]["claude"],
            json.loads((home/"claude/settings.json").read_text())["hooks"]["SessionStart"])
        assert data["agents"]["codex"]["state"]=="installed"
        assert manage("probe",source="claude")["verified"]
        assert get("v1/connections")["agents"]["claude"]["last"] is None
        event("claude","migrating","SessionEnd")
        event("codex","other-migrating","SessionEnd")
        manage("login",enabled=True)
        manage("finish")
        event("codex","keep","SessionStart")
        event("claude","close","SessionStart")
        before=get("v1/snapshot")["sessions"]
        assert len(before)==2
        cli("stop")
        until(lambda:not (state/"connection.json").exists())
        event("claude","close","SessionEnd")
        if os.name=="nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                registered=winreg.QueryValueEx(key,"AgentPetsHabitat")[0]
            subprocess.run(registered,env=env,check=True,timeout=30)
        elif sys.platform=="darwin":
            entry=home/"Library/LaunchAgents/io.agentpets.habitat.plist"
            run(plistlib.loads(entry.read_bytes())["ProgramArguments"],env=env)
        else:
            entry=home/"config/autostart/agent-pets-habitat.desktop"
            command=next(line[5:] for line in entry.read_text().splitlines() if line.startswith("Exec="))
            run(shlex.split(command),env=env)
        assert get("v1/snapshot")["sessions"]==[before[0]]
        pointer=(root/"current").read_bytes()
        old_hooks=(home/"codex/hooks.json").read_bytes()
        install(second)
        assert (root/"current").read_bytes()!=pointer
        assert get("v1/snapshot")["sessions"]==[before[0]]
        assert (home/"codex/hooks.json").read_bytes()==old_hooks
        assert get("v1/connections")["login"]
        event("codex","keep","Stop")
        after = get("v1/snapshot")["sessions"]
        assert after[0]["attention"]=="ready", (after, get("v1/connections")["agents"]["codex"])
        # An incomplete previous release must be rejected before stopping the current host.
        previous_manifest = root/"releases"/pointer.decode()/"release.json"
        manifest = previous_manifest.read_bytes()
        active_pid = info()["pid"]
        try:
            previous_manifest.write_bytes(manifest + b" ")
            failed = subprocess.run([stable,"rollback-desktop"],env=env,timeout=30)
            assert failed.returncode != 0
            assert info()["pid"] == active_pid and get("v1/snapshot")["sessions"] == after
        finally:
            previous_manifest.write_bytes(manifest)
        cli("rollback-desktop")
        assert (root/"current").read_bytes()==pointer
        assert get("v1/snapshot")["sessions"]==after
        assert (home/"codex/hooks.json").read_bytes()==old_hooks
        cli("uninstall-desktop")
        until(lambda:not root.exists())
        for profile,file in [("claude","settings.json"),("codex","hooks.json")]:
            assert json.loads((home/profile/file).read_text())==original
        assert (state/"sessions.json").exists()
        if os.name=="nt":
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                try:
                    winreg.QueryValueEx(key,"AgentPetsHabitat")
                except FileNotFoundError:
                    pass
                else:
                    raise AssertionError("Uninstall left sign-in registration behind")
        else:
            assert not entry.exists()
        install(second)
        cli("launch","--background")
        assert all(a["state"]=="available" for a in get("v1/connections")["agents"].values())
        assert manage("install",source="codex")["verified"]
        assert get("v1/connections")["agents"]["claude"]["state"]=="available"
        sentinel = state/"unrelated-user-file"
        sentinel.write_text("keep me")
        cli("uninstall-desktop","--purge-data")
        until(lambda:not root.exists())
        assert sentinel.read_text()=="keep me"
        assert not (state/"sessions.json").exists() and not (state/"activity.sqlite3").exists()
        print("Packaged migration, login, offline close, upgrade, rollback and both uninstall modes passed",sys.platform)


if __name__ == "__main__":
    main(*[Path(arg).resolve() for arg in sys.argv[1:]])
