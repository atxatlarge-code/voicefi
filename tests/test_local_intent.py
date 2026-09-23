"""
Unit tests for VoiceFi LocalIntentRouter and on-device triage.
"""

from voicefi.local.intent import LocalIntentRouter
from voicefi.config import VoiceFiConfig


def test_heuristic_classification():
    router = LocalIntentRouter(config=VoiceFiConfig())

    # Local commands
    assert router._heuristic_classify("What branch am I on?")["target"] == "local_command"
    assert router._heuristic_classify("Check the battery level")["target"] == "local_command"
    assert router._heuristic_classify("What time is it right now?")["target"] == "local_command"
    assert router._heuristic_classify("Please stop speech")["target"] == "local_command"

    # Obsidian
    assert router._heuristic_classify("Add to obsidian: buy coffee")["target"] == "obsidian"
    assert router._heuristic_classify("Log this note: refactor database")["target"] == "obsidian"

    # Codex / ChatGPT
    assert router._heuristic_classify("Ask codex to generate tests")["target"] == "codex"
    assert router._heuristic_classify("Send this to chatgpt")["target"] == "codex"

    # Claude Code
    assert router._heuristic_classify("Ask claude to run the build script")["target"] == "claude"

    # Antigravity (Default coding)
    assert router._heuristic_classify("Refactor authentication token handler")["target"] == "antigravity"


def test_execute_local_command():
    router = LocalIntentRouter(config=VoiceFiConfig())

    # Time command
    time_res = router.execute_local_command("What time is it?")
    assert "It is" in time_res

    # Branch command
    branch_res = router.execute_local_command("What branch am I on?")
    assert "branch" in branch_res.lower() or "repository" in branch_res.lower()

    # Battery command
    batt_res = router.execute_local_command("Check battery")
    assert "battery" in batt_res.lower() or "unable" in batt_res.lower()


def test_route_prompt():
    router = LocalIntentRouter(config=VoiceFiConfig())

    # Empty prompt
    assert router.route_prompt("")["status"] == "empty"

    # Local command routing
    r_local = router.route_prompt("What time is it?")
    assert r_local["status"] == "handled_local"
    assert r_local["target"] == "local_command"
    assert "It is" in r_local["spoken_response"]

    # Claude routing
    r_claude = router.route_prompt("Ask claude to test")
    assert r_claude["status"] == "routed_agent"
    assert r_claude["target"] == "claude"

    # Codex routing
    r_codex = router.route_prompt("Ask codex to explain this")
    assert r_codex["status"] == "routed_agent"
    assert r_codex["target"] == "codex"
