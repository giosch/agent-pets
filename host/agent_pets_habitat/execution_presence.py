"""Release native Codex command approvals only after exact execution evidence."""
from collections import Counter
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

UTF8_PREFIX = "try { [Console]::OutputEncoding=[System.Text.Encoding]::UTF8 } catch {}\n"
SHELLS = {"pwsh.exe", "powershell.exe", "cmd.exe", "bash.exe", "sh.exe"}


def command_key(command):
    if not isinstance(command, str) or not command:
        return ""
    command = command.replace("\r\n", "\n")
    if command.startswith(UTF8_PREFIX):
        command = command[len(UTF8_PREFIX):]
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def windows_argv(command_line):
    from ctypes import wintypes
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = (wintypes.HLOCAL,)
    count = ctypes.c_int()
    argv = shell.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not argv:
        return []
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(argv)


def script_from_argv(argv):
    # A shell command is an argument, never parsed/evaluated as shell code here.
    for i, value in enumerate(argv[1:], 1):
        if value.lower() in {"-command", "-c", "-lc", "/c"} and i + 1 < len(argv):
            return argv[i + 1] if i + 2 == len(argv) else ""
    return ""


def running_commands(owner_pids):
    if os.name != "nt" or not owner_pids:
        return []
    owners = sorted({int(p) for p in owner_pids if type(p) is int and 0 < p <= 0x7fffffff})
    if not owners:
        return []
    condition = " OR ".join("ParentProcessId=" + str(p) for p in owners[:128])
    code = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;$ErrorActionPreference='Stop';Get-CimInstance Win32_Process -Filter '" + condition +
            "' | Where-Object {$_.Name -in @('pwsh.exe','powershell.exe','cmd.exe','bash.exe','sh.exe')} | "
            "ForEach-Object {[pscustomobject]@{pid=$_.ProcessId;owner=$_.ParentProcessId;"
            "started=([DateTimeOffset]$_.CreationDate).ToUnixTimeMilliseconds()/1000.0;command=$_.CommandLine}} | ConvertTo-Json -Compress")
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", code],
                                capture_output=True, text=True, encoding="utf-8", timeout=3,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode or not result.stdout.strip():
            return []
        records = json.loads(result.stdout)
        if isinstance(records, dict): records = [records]
        found = []
        for record in records:
            script = script_from_argv(windows_argv(record.get("command", "")))
            key = command_key(script)
            if key:
                found.append({"pid":record["pid"], "owner":record["owner"], "started":record["started"], "key":key})
        return found
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return []


def resolved_calls(calls, processes, owner_identity):
    # Duplicate commands are deliberately ambiguous. No timing-only release.
    counts = Counter((c["owner_pid"], c["command_key"]) for c in calls)
    resolved = []
    for call in calls:
        if not call.get("waiting") or counts[(call["owner_pid"], call["command_key"])] != 1:
            continue
        if owner_identity(call["owner_pid"]) != call["owner_start"]:
            continue
        matches = [p for p in processes if p["owner"] == call["owner_pid"] and
                   p["key"] == call["command_key"] and p["started"] >= call["observed"]]
        if len(matches) == 1:
            resolved.append(call)
    return resolved


class ExecutionPresence:
    def __init__(self, scanner=running_commands):
        self.scanner = scanner
        self.next_check = 0

    def reconcile(self, habitat):
        if time.monotonic() < self.next_check:
            return
        self.next_check = time.monotonic() + 1
        with habitat.lock:
            calls = []
            for session in habitat.sessions.values():
                if not session.id.startswith("codex:"):
                    continue
                for ref, metadata in session.call_metadata.items():
                    calls.append(dict(metadata, session=session.id.split(":",1)[1], ref=ref,
                                      turn=session.turn, waiting=session.waits.get(ref)=="approval"))
        if not any(c["waiting"] for c in calls):
            return
        from .presence import process_info
        def identity(pid):
            info = process_info(pid)
            return info[2] if info else None
        processes = self.scanner({c["owner_pid"] for c in calls})
        from .adapters import Signal
        for call in resolved_calls(calls, processes, identity):
            habitat.apply(Signal("codex",call["session"],"approval_resolved",turn=call["turn"],ref=call["ref"]))
