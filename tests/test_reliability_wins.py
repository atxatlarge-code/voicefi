"""
Unit tests for VoiceFi Reliability Wins:
1. Deterministic STT Hallucination Loop Stripper (collapse_repetitive_artifacts)
2. Zero-Config MCP Client-ID Auto-Binding (detect_calling_client_identity)
3. macOS Cooperative Application Activation (cooperative_activate_app)
"""

import os
import pytest
from voicefi.tts.normalizer import collapse_repetitive_artifacts
from voicefi.mcp_server import detect_calling_client_identity
from voicefi.integrations.injector import cooperative_activate_app


class TestRepetitiveArtifactCollapser:
    def test_strip_single_word_loop(self):
        corrupted = "Check this URL URL URL URL URL URL URL now"
        cleaned = collapse_repetitive_artifacts(corrupted)
        assert cleaned == "Check this now"

    def test_strip_multi_word_phrase_loop(self):
        corrupted = (
            "Let us check the git diff. "
            "Thank you for watching! Thank you for watching! "
            "Thank you for watching! Thank you for watching! "
            "Thank you for watching! Thank you for watching!"
        )
        cleaned = collapse_repetitive_artifacts(corrupted)
        assert cleaned == "Let us check the git diff."

    def test_strip_cjk_loop(self):
        corrupted = "这是测试谢谢观看谢谢观看谢谢观看谢谢观看谢谢观看谢谢观看完成"
        cleaned = collapse_repetitive_artifacts(corrupted)
        assert "谢谢观看" not in cleaned
        assert "这是测试" in cleaned
        assert "完成" in cleaned

    def test_preserves_rhetorical_repetition(self):
        # 3 repeats should stay intact
        rhetorical = "No, no, no, that is not what I meant. Yeah yeah yeah!"
        cleaned = collapse_repetitive_artifacts(rhetorical)
        assert cleaned == rhetorical

    def test_clean_text_untouched(self):
        clean = "Refactor the authentication middleware and test all endpoints."
        assert collapse_repetitive_artifacts(clean) == clean

    def test_pure_hallucination_loop_stripped(self):
        corrupted = "thanks for watching! " * 100
        assert collapse_repetitive_artifacts(corrupted) == ""

    def test_large_scale_hallucination_performance(self):
        import time
        corrupted = "Valid speech prompt. " + ("Please like and subscribe! " * 200)
        t0 = time.perf_counter()
        cleaned = collapse_repetitive_artifacts(corrupted)
        dt_ms = (time.perf_counter() - t0) * 1000
        assert cleaned == "Valid speech prompt."
        assert dt_ms < 15.0, f"Expected <15ms, took {dt_ms:.2f}ms"

    def test_strip_sentence_level_duplicate(self):
        corrupted = "Let us check the git diff. Let us check the git diff."
        cleaned = collapse_repetitive_artifacts(corrupted)
        assert cleaned == "Let us check the git diff."

    def test_strip_unpunctuated_phrase_duplicate(self):
        corrupted = (
            "if you need to you can open up companion on the desktop "
            "if you need to you can open up companion on the desktop"
        )
        cleaned = collapse_repetitive_artifacts(corrupted)
        assert cleaned == "if you need to you can open up companion on the desktop"

    def test_empty_and_whitespace(self):
        assert collapse_repetitive_artifacts("") == ""
        assert collapse_repetitive_artifacts("   ") == "   "
        assert collapse_repetitive_artifacts(None) is None


class TestMCPClientIdDetection:
    def test_voicefi_client_id_env_override(self, monkeypatch):
        monkeypatch.setenv("VOICEFI_CLIENT_ID", "claude")
        assert detect_calling_client_identity() == "claude"

    def test_voicebox_client_id_env_override(self, monkeypatch):
        monkeypatch.delenv("VOICEFI_CLIENT_ID", raising=False)
        monkeypatch.setenv("VOICEBOX_CLIENT_ID", "cursor")
        assert detect_calling_client_identity() == "cursor"

    def test_handshake_name_mapping(self, monkeypatch):
        monkeypatch.delenv("VOICEFI_CLIENT_ID", raising=False)
        monkeypatch.delenv("VOICEBOX_CLIENT_ID", raising=False)

        assert detect_calling_client_identity("claude-code") == "claude"
        assert detect_calling_client_identity("Claude Desktop") == "claude"
        assert detect_calling_client_identity("Cursor/0.45.0") == "cursor"
        assert detect_calling_client_identity("windsurf-ide") == "windsurf"
        assert detect_calling_client_identity("Antigravity") == "antigravity"


class TestCooperativeActivation:
    def test_cooperative_activate_none_target(self):
        assert cooperative_activate_app(None) is False
