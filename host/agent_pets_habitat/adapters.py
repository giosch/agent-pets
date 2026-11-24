"""Translate local agent hooks before sending them to the habitat host."""
from dataclasses import dataclass
import re

from agent_pets_daemon.protocol import ASK_USER_QUESTION_TOOL, hook_payload_to_daemon_message

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
    "retry", "interrupt", "fork", "observe", "owner_exit", "dismissed", "approval_resolved",
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
    if words and words[0] in {"cp", "mv", "scp", "rsync", "copy-item", "move-item", "robocopy"}:
        return "transferring"
    if words and (words[0] in {"make", "ninja", "msbuild"} or words[:2] in
                  (["cmake", "--build"], ["cargo", "build"], ["dotnet", "build"], ["go", "build"])
                  or words[:3] == ["npm", "run", "build"]):
        return "building"
    if words and (words[0] in _INSPECT_COMMANDS or " ".join(words[:2]) in _INSPECT_COMMANDS):
        return "inspecting"
    return activity


def _claude_background(hook, kind, tool):
    """Reduce task metadata locally; never forward commands, output or prompts."""
    started, finished, tasks = "", "", None
    response = hook.get("tool_response")
    arguments = hook.get("tool_input")
    if kind == "done" and isinstance(response, dict):
        if tool in {"Bash", "PowerShell"}:
            started = response.get("backgroundTaskId") or ""
        if tool == "TaskStop" or (tool == "TaskOutput" and
                isinstance(response.get("task"), dict) and
                response["task"].get("status") in {"completed", "failed", "killed", "stopped"}):
            if isinstance(arguments, dict):
                finished = arguments.get("task_id") or ""
    if kind == "prompt":
        prompt = hook.get("prompt")
        if isinstance(prompt, str) and prompt.lstrip().startswith("<task-notification>"):
            task = re.search(r"<task-id>([\w-]{1,512})</task-id>", prompt)
            status = re.search(r"<status>(completed|failed|killed|stopped)</status>", prompt)
            if task and status:
                finished = task[1]
    if kind == "ready" and isinstance(hook.get("background_tasks"), list):
        tasks = {}
        for task in hook["background_tasks"][:128]:
            if not isinstance(task, dict) or task.get("status") not in {"running", "pending", "queued"}:
                continue
            ident = task.get("id")
            if not isinstance(ident, str) or not 0 < len(ident) <= 512:
                continue
            label = task.get("type")
            if label in {"shell", "monitor"}:
                activity = _activity("Bash", {"command": task.get("command")})
            elif label in {"subagent", "teammate", "workflow", "cloud session"}:
                activity = "coordinating"
            else:
                activity = "external"
            tasks[ident] = activity
    started = started if isinstance(started, str) and len(started) <= 512 else ""
    finished = finished if isinstance(finished, str) and len(finished) <= 512 else ""
    return started, finished, tasks


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
    event: str = ""
    owner_pid: int = 0
    owner_start: str = ""
    transient_fork: bool = False
    background_ref: str = ""
    finished_background: str = ""
    background_tasks: dict[str, str] | None = None
    progress_done: int = -1
    progress_total: int = 0
    progress_kind: str = ""
    command_key: str = ""

    def __post_init__(self):
        if type(self.transient_fork) is not bool or (self.transient_fork and
                (self.source != "codex" or self.kind != "fork")):
            raise ValueError("Invalid transient fork")
        if type(self.owner_pid) is not int or not 0 <= self.owner_pid <= 0x7fffffff or not isinstance(self.owner_start, str) or len(self.owner_start) > 64:
            raise ValueError("Invalid process identity")
        allowed = {"working", "external", "building", "transferring", *ACTIVITIES.values()}
        if self.background_tasks is not None and (not isinstance(self.background_tasks, dict) or
                len(self.background_tasks) > 128 or any(
                    not isinstance(k, str) or not 0 < len(k) <= 512 or
                    not isinstance(v, str) or v not in allowed for k, v in self.background_tasks.items())):
            raise ValueError("Invalid background task state")
        if (type(self.progress_done) is not int or type(self.progress_total) is not int or
                self.progress_kind not in {"", "steps", "tasks"} or
                (self.progress_kind and not 0 <= self.progress_done <= self.progress_total <= 100000) or
                (not self.progress_kind and (self.progress_done != -1 or self.progress_total != 0))):
            raise ValueError("Invalid reported progress")
        if not isinstance(self.command_key, str) or (self.command_key and not re.fullmatch("[0-9a-f]{64}", self.command_key)):
            raise ValueError("Invalid command fingerprint")
        fields = (self.session, self.turn, self.ref, self.tool, self.background_ref, self.finished_background)
        if not all(isinstance(v, str) and len(v) <= 512 for v in fields):
            raise ValueError("Invalid hook identifier")
        if self.source not in SOURCES or self.kind not in KINDS or not self.session:
            raise ValueError("Unknown source, session or event")
        if self.event and self.event not in HOOKS[self.source]:
            raise ValueError("Unknown hook name")
        if self.activity not in {"", "working", "external", "building", "transferring", *ACTIVITIES.values()}:
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
    kind = "fork" if event == "SessionStart" and hook.get("source") == "fork" else EVENTS[event]
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
    # Private sampling forks have no transcript. A missing field is an older client,
    # and ordinary persisted forks are real chats, so keep both visible.
    transient = (source == "codex" and kind == "fork" and
                 "transcript_path" in hook and hook["transcript_path"] is None)
    background_ref, finished, tasks = _claude_background(hook, kind, tool) if source == "claude" else ("", "", None)
    if background_ref:
        activity = _activity(tool, hook.get("tool_input"))
    done, total, progress_kind = -1, 0, ""
    if kind == "done":
        items = None
        if tool == "update_plan" and isinstance(hook.get("tool_input"), dict):
            items, progress_kind = hook["tool_input"].get("plan"), "steps"
        elif source == "claude" and tool == "TaskList":
            result = hook.get("tool_response")
            items, progress_kind = (result.get("tasks") if isinstance(result, dict) else result), "tasks"
        if (isinstance(items, list) and len(items) <= 100000 and
                all(isinstance(item, dict) and item.get("status") in {"pending", "in_progress", "completed"} for item in items)):
            done, total = sum(item["status"] == "completed" for item in items), len(items)
        else:
            progress_kind = ""
    key = ""
    if source == "codex" and kind in {"tool", "approval"} and tool in {"Bash", "PowerShell", "exec_command"}:
        args = hook.get("tool_input")
        if isinstance(args, dict):
            from .execution_presence import command_key
            key = command_key(args.get("command", args.get("cmd")))
    return Signal(source, session, kind, hook.get("turn_id") or "", ref, tool, activity, event,
                  transient_fork=transient, background_ref=background_ref,
                  finished_background=finished, background_tasks=tasks,
                  progress_done=done, progress_total=total, progress_kind=progress_kind, command_key=key)
