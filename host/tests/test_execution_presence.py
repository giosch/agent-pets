"""No approval release without unique current, exact execution evidence."""
from unittest.mock import patch
from agent_pets_habitat.execution_presence import command_key, resolved_calls, script_from_argv, UTF8_PREFIX, ExecutionPresence
from agent_pets_habitat.adapters import Signal, normalize
from agent_pets_habitat.model import Habitat
from agent_pets_habitat.presence import codex_owner, claude_owner


def call(ref="a", **changes):
    return dict({"session":"chat", "ref":ref, "turn":"", "owner_pid":42,"owner_start":"generation",
                 "command_key":command_key("sleep 60"),"observed":100,"waiting":True}, **changes)

def process(**changes):
    return dict({"pid":60,"owner":42,"key":command_key("sleep 60"),"started":101}, **changes)


def test_unique_current_command_releases_only_its_matching_approval():
    a = call()
    assert resolved_calls([a], [process()], lambda p:"generation") == [a]
    assert resolved_calls([a], [], lambda p:"generation") == []
    assert resolved_calls([a], [process(key=command_key("something else"))], lambda p:"generation") == []
    assert resolved_calls([a], [process(owner=99)], lambda p:"generation") == []
    assert resolved_calls([a], [process(started=99)], lambda p:"generation") == []
    assert resolved_calls([a], [process()], lambda p:"reused pid") == []


def test_duplicate_commands_and_multiple_processes_remain_ambiguous():
    assert resolved_calls([call(),call("b",waiting=False)], [process()], lambda p:"generation") == []
    assert resolved_calls([call()], [process(),process(pid=61)], lambda p:"generation") == []


def test_exact_native_encoding_prefix_is_removed_but_other_code_is_not():
    assert command_key(UTF8_PREFIX + "sleep 60") == command_key("sleep 60")
    assert command_key("write-output hi; sleep 60") != command_key("sleep 60")
    assert script_from_argv(["pwsh.exe","-Command","sleep 60"]) == "sleep 60"
    assert script_from_argv(["pwsh.exe","-Command","sleep","60"]) == ""
    assert script_from_argv(["anything.exe","--other","sleep 60"]) == ""


def test_fingerprints_do_not_keep_commands_and_disambiguate_parallel_permission_requests():
    h = Habitat();h.apply(Signal("codex","chat","prompt"))
    for ref,command in [("a","sleep 60"),("b","Get-Content file")]:
        h.apply(Signal("codex","chat","tool",ref=ref,tool="Bash",activity="executing",
                       command_key=command_key(command),owner_pid=42,owner_start="generation"),observed=100)
    signal = normalize("codex",{"session_id":"chat","hook_event_name":"PermissionRequest","tool_name":"Bash","tool_input":{"command":"sleep 60"}})
    h.apply(signal)
    assert h.sessions["codex:chat"].waits == {"a":"approval"}
    assert "sleep 60" not in str(h.sessions["codex:chat"].call_metadata)
    monitor=ExecutionPresence(scanner=lambda owners:[process()])
    with patch("agent_pets_habitat.presence.process_info",return_value=(1,"codex.exe","generation")):
        monitor.reconcile(h)
    assert h.snapshot()["sessions"][0]["attention"] == "none"
    assert h.snapshot()["sessions"][0]["active_calls"] == 2


def test_venv_launchers_are_followed_to_the_native_agent():
    parents={10:(11,"python.exe","a"),11:(12,"powershell.exe","b"),12:(1,"codex.exe","generation")}
    with patch("agent_pets_habitat.presence.os.getppid",return_value=10),patch("agent_pets_habitat.presence.process_info",side_effect=lambda p:parents[p]):
        assert codex_owner() == (12,"generation")
        assert claude_owner() == (0,"")


def test_permission_before_tool_start_is_bound_by_exact_command():
    h = Habitat();h.apply(Signal("codex","chat","prompt"))
    key=command_key("sleep 60")
    h.apply(Signal("codex","chat","approval",tool="Bash",command_key=key))
    assert h.sessions["codex:chat"].waits == {"command:"+key:"approval"}
    h.apply(Signal("codex","chat","tool",ref="unrelated",tool="Bash",command_key=command_key("other"),owner_pid=42,owner_start="generation"),observed=100)
    assert h.sessions["codex:chat"].waits == {"command:"+key:"approval"}
    h.apply(Signal("codex","chat","tool",ref="right",tool="Bash",command_key=key,owner_pid=42,owner_start="generation"),observed=100)
    assert h.sessions["codex:chat"].waits == {"right":"approval"}


def test_unmatched_fingerprint_does_not_attach_to_an_unrelated_single_call():
    h=Habitat();h.apply(Signal("codex","chat","tool",ref="other",tool="Bash",command_key=command_key("other"),owner_pid=42,owner_start="generation"),observed=100)
    key=command_key("pending")
    h.apply(Signal("codex","chat","approval",tool="Bash",command_key=key))
    assert h.sessions["codex:chat"].waits == {"command:"+key:"approval"}
    h.apply(Signal("codex","chat","done",ref="other",tool="Bash"))
    assert h.snapshot()["sessions"][0]["attention"] == "approval"
