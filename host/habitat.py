#!/usr/bin/env python3
"""Launch the local habitat, register agent hooks, or manage renderer packs."""
import argparse
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import sys
import threading
import webbrowser

from clawd_tank_daemon.session_store import write_json_atomic
from clawd_tank_habitat.adapters import SOURCES


@contextmanager
def state_owner(directory: Path):
    """One writer per state directory, even when starting on a different port."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "host.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(f"A habitat already owns {directory}") from error
        yield


def run_demo(habitat, stop):
    from clawd_tank_habitat.adapters import normalize
    events = [
        ("claude", "a", "PreToolUse", "Edit"), ("codex", "b", "PreToolUse", "Bash"),
        ("claude", "c", "PreToolUse", "Read"), ("codex", "d", "PreToolUse", "apply_patch"),
        ("codex", "d", "PermissionRequest", "apply_patch"), ("claude", "a", "Stop", ""),
        ("codex", "d", "PostToolUse", "apply_patch"), ("claude", "a", "UserPromptSubmit", ""),
    ]
    while not stop.is_set():
        for index, (source, session, event, tool) in enumerate(events):
            signal = normalize(source, {"hook_event_name": event, "session_id": session, "tool_name": tool})
            habitat.apply(signal)
            if stop.wait(0.4 if index < 3 else 3.2):
                return
        for session, source in zip("abcd", ("claude", "codex", "claude", "codex")):
            habitat.apply(normalize(source, {"hook_event_name": "SessionEnd", "session_id": session}))
        if stop.wait(2):
            return


def serve(args, directory):
    from clawd_tank_habitat.model import Habitat
    from clawd_tank_habitat.server import HabitatServer
    from clawd_tank_habitat.themes import Themes

    with nullcontext() if args.demo else state_owner(directory):
        habitat = Habitat(None if args.demo else directory / "sessions.json")
        with HabitatServer(args.port, habitat, Themes(directory / "packs"), demo=args.demo) as server:
            info = directory / "connection.json"
            stop = threading.Event()
            if args.demo:
                threading.Thread(target=run_demo, args=(habitat, stop), daemon=True).start()
            else:
                write_json_atomic(info, {"port": server.server_port, "key": server.key})
            url = f"http://127.0.0.1:{server.server_port}/"
            print(f"{'Demo' if args.demo else 'Live'} habitat at {url}", flush=True)
            try:
                if args.open:
                    webbrowser.open(url)
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                stop.set()
                if not args.demo:
                    info.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path,
                        default=Path(os.environ.get("CLAWD_HABITAT_HOME", Path.home() / ".clawd-tank" / "habitat")))
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("serve", help="Serve the browser habitat on loopback")
    start.add_argument("--port", type=int, default=19873)
    start.add_argument("--open", action="store_true", help="Open a local browser tab")
    start.add_argument("--demo", action="store_true", help="Play an isolated four-session scenario")
    hook = commands.add_parser("hook", help="Read one runtime hook from standard input")
    hook.add_argument("source", choices=SOURCES)
    for command in ("install-hooks", "uninstall-hooks"):
        sub = commands.add_parser(command)
        sub.add_argument("source", choices=(*SOURCES, "both"), default="both", nargs="?")
    export = commands.add_parser("export-pack", help="Export a self-contained SVG renderer pack")
    export.add_argument("kind", choices=["character", "habitat"])
    export.add_argument("id")
    export.add_argument("destination", type=Path)
    install = commands.add_parser("install-pack", help="Install a pack for the browser renderer")
    install.add_argument("archive", type=Path)
    args = parser.parse_args()
    directory = args.state_dir.expanduser().resolve()
    if args.command == "serve":
        serve(args, directory)
    elif args.command == "hook":
        from clawd_tank_habitat.hooks import forward
        forward(args.source, directory, sys.stdin.buffer)
        if args.source == "codex":
            print("{}")
    elif args.command in {"install-hooks", "uninstall-hooks"}:
        from clawd_tank_habitat.hooks import configure
        for source in SOURCES if args.source == "both" else (args.source,):
            print(configure(source, directory, remove=args.command == "uninstall-hooks"))
    elif args.command == "export-pack":
        from clawd_tank_habitat.themes import Themes
        pack = Themes(directory / "packs").packs.get((args.kind, args.id))
        if not pack:
            parser.error(f"Unknown {args.kind} pack {args.id}")
        pack.archive(args.destination)
        print(args.destination)
    else:
        from clawd_tank_habitat.themes import install_pack
        print(install_pack(args.archive, directory / "packs"))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"Habitat: {error}", file=sys.stderr)
        sys.exit(1)
