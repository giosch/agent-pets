"""Exercise the early-tester archive install and upgrade using a private pipx home."""
import functools
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]


def test_install_upgrade():
    with tempfile.TemporaryDirectory(prefix="clawd pipx ") as tmp:
        home = Path(tmp)
        env = {**os.environ, "PIPX_HOME": str(home / "pipx"), "PIPX_BIN_DIR": str(home / "bin"),
               "PIPX_DEFAULT_PYTHON": sys.executable, "AGENT_PETS_HOME": str(home / "state"),
               "CODEX_HOME": str(home / "codex"), "CLAUDE_CONFIG_DIR": str(home / "claude")}
        env.pop("PYTHONPATH", None)

        def run(*args, **kwargs):
            return subprocess.run(args, cwd=home, env=env, check=True, timeout=180, **kwargs)

        # Build the source distribution once so missing packaged code/artwork fails the test.
        run(sys.executable, "-m", "build", "--sdist", "--no-isolation", "--outdir", tmp, str(ROOT))
        shutil.unpack_archive(next(home.glob("*.tar.gz")), home / "source")
        source, = (home / "source").iterdir()
        project = source / "pyproject.toml"
        original = project.read_text(encoding="utf-8")

        downloads = home / "downloads"
        downloads.mkdir()
        archive = downloads / "master.zip"

        def publish(version):
            project.write_text(re.sub(r'(?m)^version = ".*"$', f'version = "{version}"', original), encoding="utf-8")
            with ZipFile(archive, "w") as bundle:
                for file in source.rglob("*"):
                    if file.is_file():
                        bundle.write(file, file.relative_to(source.parent))

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=downloads)
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{server.server_port}/master.zip"
            app = home / "bin" / ("agent-pets.exe" if os.name == "nt" else "agent-pets")
            pipx = [sys.executable, "-m", "pipx"]
            configs = {"claude": home / "claude/settings.json", "codex": home / "codex/hooks.json"}

            def send(source_name, event):
                groups = json.loads(configs[source_name].read_bytes())["hooks"][event]
                hook, = [h for g in groups for h in g["hooks"] if h.get("statusMessage") == "Updating Agent Pets habitat"]
                if source_name == "claude":
                    cmd = [hook["command"], *hook["args"]]
                elif os.name == "nt":
                    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", hook["commandWindows"]]
                else:
                    cmd = ["/bin/sh", "-c", hook["command"]]
                run(*cmd, input=json.dumps({"hook_event_name": event, "session_id": "early-test"}).encode())

            def verify_host(attention):
                with subprocess.Popen([app, "serve", "--port", "0"], env=env, cwd=home,
                                      stdout=subprocess.PIPE, text=True) as host:
                    try:
                        base = host.stdout.readline().split()[-1]
                        with urllib.request.urlopen(base + "v1/snapshot", timeout=5) as response:
                            sessions = json.load(response)["sessions"]
                        assert {s["id"]: s["attention"] for s in sessions} == {
                            "claude:early-test": attention, "codex:early-test": attention}
                        with urllib.request.urlopen(base + "art/character/clawd/editing", timeout=5) as response:
                            assert b"<svg" in response.read()
                    finally:
                        if host.poll() is None:
                            run(app, "stop")
                        host.wait(timeout=15)

            publish("0.0.1")
            run(*pipx, "install", url)
            run(app, "self-test")
            run(app, "install-hooks", "both")
            before = {s: path.read_bytes() for s, path in configs.items()}
            for s in configs:
                send(s, "UserPromptSubmit")
            verify_host("none")
            publish("0.0.2")
            run(*pipx, "upgrade", "agent-pets-habitat")
            metadata = json.loads(run(*pipx, "list", "--json", capture_output=True).stdout)
            assert metadata["venvs"]["agent-pets-habitat"]["metadata"]["main_package"]["package_version"] == "0.0.2"
            for s, path in configs.items():
                assert path.read_bytes() == before[s]
                send(s, "Stop")
            verify_host("ready")
            run(app, "unregister")
            run(*pipx, "uninstall", "agent-pets-habitat")
            server.shutdown()


if __name__ == "__main__":
    test_install_upgrade()
