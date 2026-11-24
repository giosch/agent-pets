"""Identify a native Claude ancestor without reading arguments or session files."""
import os
from pathlib import Path
import subprocess


def process_info(pid):
    """Return parent, executable name and start identity, False if gone, None if unknown."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.OpenProcess.restype = wintypes.HANDLE
        handle = dll.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        h = wintypes.HANDLE(handle)
        try:
            size = wintypes.DWORD(32768)
            name = ctypes.create_unicode_buffer(size.value)
            times = [wintypes.FILETIME() for _ in range(4)]
            if not dll.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
                return None
            start = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
            if times[1].dwHighDateTime or times[1].dwLowDateTime:
                return False
            if not dll.QueryFullProcessImageNameW(h, 0, name, ctypes.byref(size)):
                return None
            # PROCESS_BASIC_INFORMATION contains six pointer-sized fields.
            info = (ctypes.c_size_t * 6)()
            status = ctypes.windll.ntdll.NtQueryInformationProcess(h, 0, ctypes.byref(info), ctypes.sizeof(info), None)
            if status:
                return None
            return info[5], Path(name.value).name.lower(), str(start)
        finally:
            dll.CloseHandle(h)
    try:
        os.kill(pid, 0)
        result = subprocess.run(["ps", "-p", str(pid), "-o", "ppid=,lstart=,comm="],
                                capture_output=True, text=True, timeout=.5, env={**os.environ, "LC_ALL":"C"})
        fields = result.stdout.strip().split(None, 6)
        if result.returncode == 0 and len(fields) == 7:
            return int(fields[0]), Path(fields[6]).name.lower(), " ".join(fields[1:6])
    except ProcessLookupError:
        return False
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def agent_owner(source):
    names = {"claude", "claude.exe"} if source == "claude" else {"codex", "codex.exe"}
    pid = os.getppid()
    for _ in range(10):
        if pid <= 1:
            break
        info = process_info(pid)
        if not info:
            break
        parent, name, start = info
        if name in names:
            return pid, start
        if name not in {"sh", "bash", "dash", "zsh", "cmd.exe", "powershell.exe", "pwsh", "pwsh.exe",
                        "agent-pets.exe", "python", "python3", "python.exe", "pythonw.exe"}:
            break
        pid = parent
    return 0, ""


def claude_owner():
    return agent_owner("claude")

def codex_owner():
    return agent_owner("codex")


def owner_exited(pid, start):
    info = process_info(pid)
    return info is False or bool(info and info[2] != start)
