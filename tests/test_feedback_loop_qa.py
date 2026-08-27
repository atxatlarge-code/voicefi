"""
QA Test Suite for VoiceFi Feedback Loop, Hearing Test, and Acoustic Verification.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from voicefi.config import VoiceFiConfig
from voicefi.troubleshoot import AudioTroubleshooter, SpeechLoopbackVerification
from voicefi.cli import build_parser, cmd_feedback_loop, cmd_hearing_test, cmd_voice


class TestFeedbackLoopCLI:
    """QA test suite for Feedback Loop and Hearing Test CLI parsers and handlers."""

    def test_cli_parser_feedback_loop_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["feedback-loop"])
        assert args.command == "feedback-loop"
        assert args.voice == "Aria"
        assert args.text == "This is a test feedback loop"
        assert args.no_send is False
        assert args.conv_id is None
        assert args.hud is False
        assert args.json is False

    def test_cli_parser_feedback_loop_custom_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "feedback-loop",
            "Viv",
            "-t", "Custom verification sentence",
            "--no-send",
            "-c", "conv-test-123",
            "--hud",
            "--json",
        ])
        assert args.command == "feedback-loop"
        assert args.voice == "Viv"
        assert args.text == "Custom verification sentence"
        assert args.no_send is True
        assert args.conv_id == "conv-test-123"
        assert args.hud is True
        assert args.json is True

    def test_cli_parser_hearing_test_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "hearing-test",
            "Samantha",
            "-t", "Acoustic room verification",
            "--hud",
            "--json",
        ])
        assert args.command == "hearing-test"
        assert args.voice == "Samantha"
        assert args.text == "Acoustic room verification"
        assert args.hud is True
        assert args.json is True

    def test_cli_voice_test_feedback_loop_alias(self):
        parser = build_parser()
        args = parser.parse_args([
            "voice", "test", "Ava (Premium)",
            "--feedback-loop",
            "--no-send",
            "-c", "conv-999",
            "--json",
        ])
        assert args.command == "voice"
        assert args.voice_action == "test"
        assert args.voice == "Ava (Premium)"
        assert args.feedback_loop is True
        assert args.no_send is True
        assert args.conv_id == "conv-999"
        assert args.json is True

    def test_cmd_feedback_loop_json_output(self, capsys):
        parser = build_parser()
        args = parser.parse_args(["feedback-loop", "Aria", "--no-send", "--json"])
        
        mock_result = {
            "voice": "Aria",
            "sent_text": "This is a test feedback loop",
            "heard_text": "This is a test feedback loop",
            "success": True,
            "similarity_pct": 100.0,
            "latency_ms": 95.0,
            "duration_s": 1.1,
            "rms_energy": 0.045,
            "sent_to_agent": False,
        }
        
        with patch.object(AudioTroubleshooter, "test_feedback_loop", return_value=mock_result):
            cmd_feedback_loop(args)
            
        captured = capsys.readouterr().out
        parsed = json.loads(captured)
        assert parsed["success"] is True
        assert parsed["similarity_pct"] == 100.0
        assert parsed["sent_to_agent"] is False


class TestFeedbackLoopSimilarity:
    """QA tests for similarity scoring algorithm in test_acoustic_stt_loopback."""

    def test_exact_and_case_insensitive_match(self):
        ts = AudioTroubleshooter(VoiceFiConfig())
        fake_audio = MagicMock()
        with patch("sounddevice.rec", return_value=MagicMock()), \
             patch("sounddevice.stop"), \
             patch("sounddevice.wait"), \
             patch("soundfile.write"), \
             patch("voicefi.tts.get_tts_engine") as mock_tts, \
             patch("voicefi.stt.get_stt_engine") as mock_stt:
            mock_tts.return_value = MagicMock()
            mock_stt_inst = MagicMock()
            mock_stt.return_value = mock_stt_inst

            # 1. Exact match with punctuation difference
            mock_stt_inst.transcribe.return_value = "This is a loopback test!"
            res = ts.test_acoustic_stt_loopback(voice_name_or_id="Aria", text="this is a loopback test.")
            assert res.success is True
            assert res.similarity_pct == 100.0

            # 2. Minor word variation
            mock_stt_inst.transcribe.return_value = "This is loopback test"
            res2 = ts.test_acoustic_stt_loopback(voice_name_or_id="Aria", text="This is a loopback test")
            assert res2.success is True
            assert 75.0 <= res2.similarity_pct <= 98.0

            # 3. Completely different sentence
            mock_stt_inst.transcribe.return_value = "Unrelated background conversation"
            res3 = ts.test_acoustic_stt_loopback(voice_name_or_id="Aria", text="This is a loopback test")
            assert res3.success is True
            assert res3.similarity_pct < 30.0


class TestCompanionServerTroubleshootRoutes(AioHTTPTestCase):
    """QA tests for companion server troubleshoot feedback loop and hearing test endpoints."""

    async def get_application(self):
        from voicefi.companion.server import CompanionServer
        self.server = CompanionServer(VoiceFiConfig())
        return self.server.app

    async def test_api_troubleshoot_feedback_loop_route(self):
        mock_result = {
            "voice": "Aria",
            "sent_text": "Loop test phrase",
            "heard_text": "Loop test phrase",
            "success": True,
            "similarity_pct": 100.0,
            "latency_ms": 110.0,
            "duration_s": 1.3,
            "rms_energy": 0.038,
            "sent_to_agent": False,
        }
        with patch.object(AudioTroubleshooter, "test_feedback_loop", return_value=mock_result):
            resp = await self.client.post(
                "/api/troubleshoot/feedback_loop",
                json={"voice": "Aria", "text": "Loop test phrase", "send": False},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["similarity_pct"] == 100.0

    async def test_api_troubleshoot_hearing_test_route(self):
        mock_res = SpeechLoopbackVerification(
            voice="Aria",
            sent_text="Hearing check",
            heard_text="Hearing check",
            success=True,
            similarity_pct=100.0,
            latency_ms=90.0,
            duration_s=1.0,
            rms_energy=0.04,
        )
        with patch.object(AudioTroubleshooter, "test_hearing", return_value=mock_res):
            resp = await self.client.post(
                "/api/troubleshoot/hearing_test",
                json={"voice": "Aria", "text": "Hearing check"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["similarity_pct"] == 100.0
