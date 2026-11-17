"""Translate local agent hooks before sending them to the habitat host."""
from dataclasses import dataclass
import re

from clawd_tank_daemon.protocol import ASK_USER_QUESTION_TOOL, hook_payload_to_daemon_message

SOURCES = ("claude", "codex")
COMMON_HOOKS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PermissionRequest", "PreCompact", "Stop", "SubagentStart", "SubagentStop",
)
HOOKS = {
    "claude": (*COMMON_HOOKS, "PostToolUseFailure", "StopFailure", "Notification"),
    "codex": (*COMMON_HOOKS, "PostModelRequest", "Interrupt"),
}
ACTIVITIES = {
    "Read": "inspecting", "Grep": "inspecting", "Glob": "inspecting",
    "Edit": "editing", "Write": "editing", "NotebookEdit": "editing", "apply_patch": "editing",
    "Bash": "executing", "PowerShell": "executing", "exec_command": "executing",
    "WebSearch": "researching", "WebFetch": "researching",
    "Agent": "coordinating", "Task": "coordinating", "spawn_agent": "coordinating",
    "wait_agent": "coordinating", "send_message": "coordinating", "LSP": "inspecting",
}
KINDS = {
    "open", "close", "prompt", "tool", "done", "question", "approval", "tool_error",
    "ready", "idle_reminder", "failure", "compact", "helper_join", "helper_leave",
    "retry", "interrupt",
}

_INSPECT_COMMANDS = {
    "cat", "dir", "findstr", "get-childitem", "get-content", "git diff", "git log",
    "git show", "git status", "grep", "head", "ls", "pwd", "rg", "select-string", "tail",
}


def _activity(tool: str, arguments) -> str:
    activity = ACTIVITIES.get(tool, "external" if tool.startswith("mcp__") else "working")
    if activity != "executing" or not isinstance(arguments, dict):
        return activity
    command = arguments.get("command", arguments.get("cmd"))
    if not isinstance(command, str) or re.search(r"[;&|<>\n\r$`()]", command):
        return activity
    words = command.lower().split()
    if words and (words[0] in _INSPECT_COMMANDS or " ".join(words[:2]) in _INSPECT_COMMANDS):
        return "inspecting"
    return activity


EVENTS = {
    "SessionStart": "open", "SessionEnd": "close", "UserPromptSubmit": "prompt",
    "PreToolUse": "tool", "PostToolUse": "done", "PermissionRequest": "approval",
    "PostToolUseFailure": "tool_error", "Stop": "ready", "StopFailure": "failure",
    "PreCompact": "compact", "SubagentStart": "helper_join", "SubagentStop": "helper_leave",
    "Interrupt": "interrupt", "Notification": "idle_reminder", "PostModelRequest": "retry",
}


@dataclass(frozen=True)
class Signal:
    source: str
    session: str
    kind: str
    turn: str = ""
    ref: str = ""
    tool: str = ""
    activity: str = ""

    def __post_init__(self):
        fields = (self.session, self.turn, self.ref, self.tool)
        if not all(isinstance(v, str) and len(v) <= 512 for v in fields):
            raise ValueError("Invalid hook identifier")
        if self.source not in SOURCES or self.kind not in KINDS or not self.session:
            raise ValueError("Unknown source, session or event")
        if self.activity not in {"", "working", "external", *ACTIVITIES.values()}:
            raise ValueError("Unknown activity")


def normalize(source: str, hook: dict) -> Signal | None:
    if not isinstance(hook, dict) or source not in SOURCES:
        return None
    event = hook.get("hook_event_name", "")
    if event not in HOOKS[source] or not hook.get("session_id"):
        return None
    if source == "claude":
        # Share the board adapter’s event filtering, including the idle_prompt matcher.
        message = hook_payload_to_daemon_message(hook)
        if message is None:
            return None
        session = message["session_id"]
    else:
        session = hook["session_id"]
    kind = EVENTS[event]
    tool = hook.get("tool_name") or ""
    if not isinstance(tool, str):
        return None
    # Some hosts qualify local function names. MCP tool names stay intact.
    tool = tool.removeprefix("functions.")
    ref = hook.get("tool_use_id") or ""
    if kind in {"helper_join", "helper_leave"}:
        ref = hook.get("agent_id") or ""
        if not ref:
            return None
    if kind == "retry" and hook.get("status") != "failed":
        return None
    if kind == "done" and source == "codex":
        result = hook.get("tool_response")
        if isinstance(result, dict) and (result.get("isError") is True or result.get("is_error") is True):
            kind = "tool_error"
    activity = ""
    if kind == "tool":
        if tool in {ASK_USER_QUESTION_TOOL, "request_user_input", "request_user_input_async"}:
            kind = "question"
        else:
            activity = _activity(tool, hook.get("tool_input"))
    if kind == "done" and tool == "request_user_input_async":
        # The tool has queued the question. The answer arrives as a later user message.
        return None
    return Signal(source, session, kind, hook.get("turn_id") or "", ref, tool, activity)
