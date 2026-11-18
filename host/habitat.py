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
        with HabitatServer(args.port, habitat, Themes(directory / "packs"), demo=args.demo, directory=directory) as server:
            info = directory / "connection.json"
            stop = threading.Event()
            if args.demo:
                threading.Thread(target=run_demo, args=(habitat, stop), daemon=True).start()
            else:
                server.drain()
                write_json_atomic(info, {"port": server.server_port, "key": server.key, "management": server.management,
                                         "inbox": True, "pid": os.getpid()})
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
    commands = parser.add_subparsers(dest="command")
    launcher = commands.add_parser("launch", help="Open the installed desktop habitat")
    launcher.add_argument("--background", action="store_true")
    commands.add_parser("stop", help="Stop this user’s live host")
    commands.add_parser("unregister", help="Remove installed hooks and sign-in startup")
    setup = commands.add_parser("desktop-install", help="Install or update this bundled desktop release")
    setup.add_argument("--no-open", action="store_true")
    commands.add_parser("rollback-desktop", help="Restore the previous installed release")
    uninstall = commands.add_parser("uninstall-desktop", help="Uninstall the desktop app")
    uninstall.add_argument("--purge-data", action="store_true", help="Also erase saved sessions and installed packs")
    uninstall.add_argument("--choose-data", action="store_true", help="Ask whether to keep saved habitat data")
    commands.add_parser("self-test", help="Verify the bundled runtime and artwork")
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
    if args.command == "desktop-install":
        from clawd_tank_habitat.installation import activate
        if not getattr(sys, "frozen", False):
            parser.error("Run the downloaded desktop installer")
        activate(Path(sys.executable).parent, directory, not args.no_open)
    elif args.command == "rollback-desktop":
        from clawd_tank_habitat.installation import rollback
        rollback(directory)
    elif args.command == "uninstall-desktop":
        from clawd_tank_habitat.installation import uninstall
        purge = args.purge_data
        if args.choose_data and os.name == "nt":
            import ctypes
            choice = ctypes.windll.user32.MessageBoxW(None, "Keep saved sessions, preferences and artwork for a future install?\n\nYes keeps your data. No erases it. Cancel keeps Clawd Tank installed.",
                                                       "Uninstall Clawd Tank Habitat", 0x23)
            if choice == 2:
                return
            purge = choice == 7
        uninstall(directory, purge)
    elif args.command == "self-test":
        import sqlite3
        from clawd_tank_habitat.themes import Themes
        from clawd_tank_habitat.server import WEB
        with sqlite3.connect(":memory:") as db:
            db.execute("SELECT 1")
        if ("character", "clawd") not in Themes(directory / "packs").packs or not (WEB / "connections.js").is_file():
            raise RuntimeError("Missing desktop resources")
    elif args.command in {None, "launch"}:
        from clawd_tank_habitat.desktop import launch
        launch(directory, getattr(args, "background", False))
    elif args.command == "stop":
        from clawd_tank_habitat.desktop import control
        control(directory, "stop")
    elif args.command == "unregister":
        from clawd_tank_habitat.desktop import control, login
        from clawd_tank_habitat.hooks import configure
        for source in SOURCES:
            configure(source, directory, remove=True)
        login(directory, False)
        control(directory, "stop")
    elif args.command == "serve":
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
