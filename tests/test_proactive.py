import pytest
from voicefi.config import VoiceFiConfig, ProActiveConfig, load_config, save_config
from voicefi.integrations.active_listening import (
    ActiveListeningEngine,
    SpokenIntentCategory,
    SpokenTargetChannel,
)


def test_proactive_config_defaults():
    """Verify ProActive configuration default structure."""
    cfg = VoiceFiConfig()
    assert hasattr(cfg, "proactive")
    assert cfg.proactive.feedback_loop.enabled is True
    assert cfg.proactive.feedback_loop.chime_cue is True
    assert cfg.proactive.feedback_loop.timeout_seconds == 12.0
    assert cfg.proactive.feedback_loop.cancel_on_typing is True
    assert cfg.proactive.meeting_assistant.enabled is False
    assert cfg.proactive.meeting_assistant.auto_notes is True
    assert cfg.proactive.meeting_assistant.auto_dispatch_subagents is True
    assert cfg.proactive.intent_routing.enabled is True


def test_proactive_config_sync(tmp_path):
    """Verify bidirectional synchronization between proactive.feedback_loop and legacy auto_listen."""
    cfg_file = tmp_path / "config.yaml"

    # Test 1: Config with proactive.feedback_loop.enabled = False
    cfg = VoiceFiConfig()
    cfg.proactive.feedback_loop.enabled = False
    save_config(cfg, target_path=cfg_file)

    loaded = load_config(str(cfg_file))
    assert loaded.proactive.feedback_loop.enabled is False
    assert loaded.antigravity.auto_listen is False
    assert loaded.claude.auto_listen is False

    # Test 2: Legacy config with antigravity.auto_listen = True
    cfg_file.write_text("antigravity:\n  auto_listen: true\n")
    loaded2 = load_config(str(cfg_file))
    assert loaded2.antigravity.auto_listen is True
    assert loaded2.proactive.feedback_loop.enabled is True


def test_intent_routing_claude():
    """Verify intent routing resolves Claude Code commands."""
    samples = [
        ("Ask Claude to run pytest on auth suite", "run pytest on auth suite"),
        ("Tell Claude to inspect the git diff", "inspect the git diff"),
        ("Claude, please check the database logs", "please check the database logs"),
        ("Send to Claude code to refactor the HUD", "refactor the HUD"),
    ]
    for raw, expected_prompt in samples:
        ch, prompt, meta = ActiveListeningEngine.resolve_target_channel(raw)
        assert ch == SpokenTargetChannel.CLAUDE, f"Failed on {raw}"
        assert expected_prompt.lower() in prompt.lower(), f"Prompt mismatch: {prompt}"

        eval_res = ActiveListeningEngine.evaluate(raw)
        assert eval_res.category == SpokenIntentCategory.ROUTED_COMMAND
        assert eval_res.target_channel == SpokenTargetChannel.CLAUDE


def test_intent_routing_slack():
    """Verify intent routing resolves Slack dispatch commands."""
    samples = [
        ("Post to Slack channel general that the tests passed", "the tests passed", "general"),
        ("Send to Slack that deployment is complete", "deployment is complete", "general"),
        ("Post in Slack #dev-standup summary of today's work", "summary of today's work", "dev-standup"),
    ]
    for raw, expected_text, expected_channel in samples:
        ch, prompt, meta = ActiveListeningEngine.resolve_target_channel(raw)
        assert ch == SpokenTargetChannel.SLACK, f"Failed on {raw}"
        assert expected_text.lower() in prompt.lower()
        assert meta.get("channel") == expected_channel

        eval_res = ActiveListeningEngine.evaluate(raw)
        assert eval_res.category == SpokenIntentCategory.ROUTED_COMMAND
        assert eval_res.target_channel == SpokenTargetChannel.SLACK


def test_intent_routing_linear():
    """Verify intent routing resolves Linear ticket creation."""
    samples = [
        ("Create a Linear ticket for memory leak in recorder", "memory leak in recorder"),
        ("Open a new Linear issue titled fix WebSocket reconnect", "fix WebSocket reconnect"),
        ("Log Linear bug high CPU usage during recording", "high CPU usage during recording"),
    ]
    for raw, expected_title in samples:
        ch, prompt, meta = ActiveListeningEngine.resolve_target_channel(raw)
        assert ch == SpokenTargetChannel.LINEAR, f"Failed on {raw}"
        assert expected_title.lower() in prompt.lower()

        eval_res = ActiveListeningEngine.evaluate(raw)
        assert eval_res.category == SpokenIntentCategory.ROUTED_COMMAND
        assert eval_res.target_channel == SpokenTargetChannel.LINEAR


def test_intent_routing_default_antigravity():
    """Verify standard developer commands route to default Antigravity channel."""
    samples = [
        "Please fix the failing unit test in test_recorder.py",
        "Add a new helper function for formatting timestamps",
        "Run pytest -v on the integration suite",
    ]
    for raw in samples:
        ch, prompt, meta = ActiveListeningEngine.resolve_target_channel(raw)
        assert ch == SpokenTargetChannel.ANTIGRAVITY
        assert prompt == raw

        eval_res = ActiveListeningEngine.evaluate(raw)
        assert eval_res.category == SpokenIntentCategory.ACTIONABLE_COMMAND
        assert eval_res.target_channel == SpokenTargetChannel.ANTIGRAVITY
