"""
Unit tests for Audio and Voice Troubleshooting Subsystem in VoiceFi.
Tests speaker chime tests, voice latency benchmarking, mic loopback,
hardware diagnostics, auto-fixes, and Web Control Panel endpoints.
"""

import json
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from voicefi.config import VoiceFiConfig
from voicefi.troubleshoot import (
    AudioTroubleshooter,
    VoiceTestResult,
    MicLoopbackResult,
    TEST_PHRASES,
)


class TestTroubleshoot(unittest.TestCase):
    def setUp(self):
        self.config = VoiceFiConfig()
        self.troubleshooter = AudioTroubleshooter(self.config)

    def test_speaker_output(self):
        """Test speaker output chime playback and latency measurement."""
        with patch("voicefi.troubleshoot.play_chime") as mock_play:
            res = self.troubleshooter.test_speaker_output("start", block=True)
            self.assertTrue(res["success"])
            self.assertEqual(res["chime"], "start")
            self.assertIn("latency_ms", res)
            mock_play.assert_called_once_with("start", block=True)

    def test_speaker_output_error(self):
        """Test speaker output error handling."""
        with patch("voicefi.troubleshoot.play_chime", side_effect=RuntimeError("Sound device unavailable")):
            res = self.troubleshooter.test_speaker_output("start", block=True)
            self.assertFalse(res["success"])
            self.assertIn("Sound device unavailable", res["error"])

    def test_voice_test_success(self):
        """Test voice audition with latency and duration reporting."""
        mock_engine = MagicMock()
        with patch("voicefi.troubleshoot.get_tts_engine", return_value=mock_engine):
            res = self.troubleshooter.test_voice(
                voice_name_or_id="Christopher",
                text="Test speech",
                provider="edge_tts",
                rate=200,
                block=True,
                show_hud=False,
            )
            self.assertTrue(res.success)
            self.assertEqual(res.voice, "en-US-ChristopherNeural")
            self.assertEqual(res.provider, "edge_tts")
            self.assertEqual(res.rate, 200)
            self.assertGreaterEqual(res.latency_ms, 0.0)
            mock_engine.speak.assert_called_once_with("Test speech", block=True)

    def test_benchmark_all_voices(self):
        """Test benchmarking curated voice personas."""
        mock_engine = MagicMock()
        with patch("voicefi.troubleshoot.get_tts_engine", return_value=mock_engine):
            benchmarks = self.troubleshooter.benchmark_all_curated_voices(voices=["Christopher", "Aria"])
            self.assertEqual(len(benchmarks), 2)
            for b in benchmarks:
                self.assertEqual(b["status"], "online")
                self.assertIn("latency_ms", b)

    def test_microphone_loopback_analysis(self):
        """Test microphone loopback capture, RMS computation, and SNR."""
        fake_audio = np.random.uniform(-0.05, 0.05, (48000, 1)).astype("float32")
        mock_sd = MagicMock()
        mock_sd.rec.return_value = fake_audio
        mock_sf = MagicMock()

        with patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}):
            with patch("voicefi.troubleshoot.open", unittest.mock.mock_open(read_data=b"RIFFtestwav")):
                res = self.troubleshooter.test_microphone_loopback(duration_seconds=1.0, play_back=False)
                self.assertTrue(res.success)
                self.assertEqual(res.duration_s, 1.0)
                self.assertGreater(res.rms_energy, 0.0)
                self.assertIsNotNone(res.base64_wav)
                self.assertTrue(res.base64_wav.startswith("data:audio/wav;base64,"))

    def test_hardware_diagnostics(self):
        """Test hardware diagnostics collection."""
        fake_devices = [
            {"name": "Built-in Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000.0},
            {"name": "Built-in Output", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
        ]
        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = fake_devices
        mock_sd.default.device = (0, 1)

        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            diag = self.troubleshooter.get_hardware_diagnostics()
            self.assertEqual(diag["default_input"], "Built-in Mic")
            self.assertEqual(diag["default_output"], "Built-in Output")
            self.assertEqual(diag["tts_provider"], self.config.tts.provider)
            self.assertEqual(diag["vad_mode"], self.config.vad.mode)

    def test_run_full_troubleshoot(self):
        """Test full troubleshooting report generation and recommendations."""
        with patch.object(self.troubleshooter, "test_speaker_output", return_value={"success": True, "latency_ms": 1.0}):
            with patch.object(self.troubleshooter, "test_voice", return_value=VoiceTestResult(voice="en-US-ChristopherNeural", provider="edge_tts", rate=200, text="test", success=True)):
                report = self.troubleshooter.run_full_troubleshoot()
                self.assertEqual(report["status"], "healthy")
                self.assertIn("hardware", report)
                self.assertIn("speaker_test", report)
                self.assertIn("active_voice_test", report)
                self.assertIn("recommendations", report)

    def test_hearing_and_full_loop(self):
        """Test hearing test and full loopback with message delivery."""
        with patch.object(self.troubleshooter, "test_acoustic_stt_loopback") as mock_acoustic:
            from voicefi.troubleshoot import SpeechLoopbackVerification
            mock_acoustic.return_value = SpeechLoopbackVerification(
                voice="Aria",
                sent_text="This is a test",
                heard_text="This is a test",
                success=True,
                similarity_pct=100.0,
                latency_ms=120.0,
                duration_s=1.2,
                rms_energy=0.015,
            )
            # Test hearing
            h_res = self.troubleshooter.test_hearing("Aria", text="This is a test")
            self.assertTrue(h_res.success)
            self.assertEqual(h_res.similarity_pct, 100.0)

            # Test full loop with dispatch
            with patch("voicefi.integrations.injector.send_message_to_agent", return_value=True) as mock_send:
                loop_res = self.troubleshooter.test_full_voice_loop("Aria", text="This is a test", send_to_conversation=True)
                self.assertTrue(loop_res["success"])
                self.assertTrue(loop_res["sent_to_agent"])
                mock_send.assert_called_once_with(conv_id=None, text="This is a test", sender_name="Aria", title="Feedback Loop (Aria)")

            # Test full loop with no-send
            with patch("voicefi.integrations.injector.send_message_to_agent", return_value=True) as mock_send:
                loop_res = self.troubleshooter.test_full_voice_loop("Aria", text="This is a test", send_to_conversation=False)
                self.assertTrue(loop_res["success"])
                self.assertFalse(loop_res["sent_to_agent"])
                mock_send.assert_not_called()

    def test_acoustic_stt_loopback_dynamic_slicing(self):
        """Test test_acoustic_stt_loopback dynamically slices recorded frames and computes accurate metrics."""
        import numpy as np
        fake_audio = np.ones((16000 * 6, 1), dtype="float32") * 0.05
        with patch("sounddevice.rec", return_value=fake_audio), \
             patch("sounddevice.stop"), \
             patch("sounddevice.wait"), \
             patch("voicefi.tts.get_tts_engine") as mock_tts_factory, \
             patch("voicefi.stt.get_stt_engine") as mock_stt_factory:
            mock_tts = MagicMock()
            mock_tts_factory.return_value = mock_tts
            mock_stt = MagicMock()
            mock_stt.transcribe.return_value = "This is a loopback test"
            mock_stt_factory.return_value = mock_stt

            res = self.troubleshooter.test_acoustic_stt_loopback(
                voice_name_or_id="Aria",
                text="This is a loopback test",
            )
            self.assertTrue(res.success)
            self.assertEqual(res.heard_text, "This is a loopback test")
            self.assertGreater(res.similarity_pct, 95.0)
            self.assertGreater(res.rms_energy, 0.0)

    @patch("voicefi.troubleshoot.save_config")
    def test_apply_fixes(self, mock_save):
        """Test applying troubleshooting fixes."""
        # 1. Reset defaults
        self.config.tts.rate = 120
        res = self.troubleshooter.apply_fix("reset_audio_defaults")
        self.assertTrue(res["success"])
        self.assertEqual(self.config.tts.rate, 200)

        # 2. Offline fallback
        res = self.troubleshooter.apply_fix("set_offline_fallback")
        self.assertTrue(res["success"])
        self.assertEqual(self.config.tts.provider, "mac_say")
        self.assertTrue(self.config.tts.voice in ("Ava (Premium)", "Ava (Enhanced)", "Ava", "Samantha"))

        # 3. Unknown fix
        res = self.troubleshooter.apply_fix("unknown_invalid_fix")
        self.assertFalse(res["success"])

    def test_ping_voice_silently_success(self):
        """Test silent voice ping latency, throughput calculation, and status."""
        mock_engine = MagicMock()
        mock_engine.speak_to_file.return_value = True
        with patch("voicefi.troubleshoot.get_tts_engine", return_value=mock_engine):
            res = self.troubleshooter.ping_voice_silently(
                voice_name_or_id="Andrew",
                text="Silent test text",
                provider="edge_tts",
            )
            self.assertTrue(res.success)
            self.assertEqual(res.voice, "en-US-AndrewNeural")
            self.assertEqual(res.provider, "edge_tts")
            self.assertEqual(res.status, "online")
            self.assertGreater(res.latency_ms, 0.0)
            self.assertGreater(res.chars_per_sec, 0.0)

    def test_ping_multiple_silently(self):
        """Test multi-ping statistics, jitter, and throughput aggregation."""
        mock_engine = MagicMock()
        mock_engine.speak_to_file.return_value = True
        with patch("voicefi.troubleshoot.get_tts_engine", return_value=mock_engine):
            stats = self.troubleshooter.ping_multiple_silently(
                voice_name_or_id="Andrew",
                count=3,
                text="Multi-ping sample phrase",
            )
            self.assertEqual(stats["count"], 3)
            self.assertEqual(stats["success_count"], 3)
            self.assertEqual(stats["success_rate_pct"], 100.0)
            self.assertIn("min_latency_ms", stats)
            self.assertIn("avg_latency_ms", stats)
            self.assertIn("max_latency_ms", stats)
            self.assertIn("jitter_ms", stats)
            self.assertIn("avg_chars_per_sec", stats)
            self.assertEqual(len(stats["pings"]), 3)


class TestTroubleshootPanelEndpoints(unittest.TestCase):
    def setUp(self):
        from voicefi.ui.panel import VoicePanelRequestHandler
        self.config = VoiceFiConfig()
        self.handler = VoicePanelRequestHandler.__new__(VoicePanelRequestHandler)
        mock_server = MagicMock()
        mock_server.config = self.config
        self.handler.server = mock_server
        self.handler.wfile = MagicMock()
        self.handler._send_json = MagicMock()

    def test_diagnostics_get(self):
        """Test GET /api/troubleshoot/diagnostics endpoint."""
        self.handler.path = "/api/troubleshoot/diagnostics"
        with patch("voicefi.troubleshoot.AudioTroubleshooter.run_full_troubleshoot", return_value={"status": "healthy"}):
            self.handler.do_GET()
            self.handler._send_json.assert_called_once()
            args, _ = self.handler._send_json.call_args
            self.assertEqual(args[0]["status"], "healthy")

    def test_ping_get(self):
        """Test GET /api/troubleshoot/ping endpoint."""
        self.handler.path = "/api/troubleshoot/ping?voice=Andrew"
        with patch("voicefi.troubleshoot.AudioTroubleshooter.ping_voice_silently") as mock_ping:
            from voicefi.troubleshoot import VoicePingResult
            mock_ping.return_value = VoicePingResult(
                voice="en-US-AndrewNeural",
                provider="edge_tts",
                persona_name="Andrew",
                success=True,
                latency_ms=180.5,
                chars_per_sec=240.0,
                words_per_min=2800.0,
                audio_bytes=14200,
                status="online",
            )
            self.handler.do_GET()
            self.handler._send_json.assert_called_once()
            args, _ = self.handler._send_json.call_args
            self.assertTrue(args[0]["success"])
            self.assertEqual(args[0]["persona_name"], "Andrew")

    def test_test_chime_post(self):
        """Test POST /api/troubleshoot/test_chime endpoint."""
        self.handler.path = "/api/troubleshoot/test_chime"
        self.handler.headers = {"Content-Length": "18"}
        self.handler.rfile = unittest.mock.mock_open(read_data=b'{"chime": "start"}')()
        with patch("voicefi.troubleshoot.AudioTroubleshooter.test_speaker_output", return_value={"success": True, "latency_ms": 1.5}):
            self.handler.do_POST()
            self.handler._send_json.assert_called_once()
            args, _ = self.handler._send_json.call_args
            self.assertTrue(args[0]["success"])

    def test_benchmark_post(self):
        """Test POST /api/troubleshoot/benchmark endpoint."""
        self.handler.path = "/api/troubleshoot/benchmark"
        self.handler.headers = {"Content-Length": "2"}
        self.handler.rfile = unittest.mock.mock_open(read_data=b"{}")()
        with patch("voicefi.troubleshoot.AudioTroubleshooter.benchmark_all_curated_voices", return_value=[{"name": "Christopher", "latency_ms": 120.0}]):
            self.handler.do_POST()
            self.handler._send_json.assert_called_once()
            args, _ = self.handler._send_json.call_args
            self.assertEqual(args[0]["status"], "success")
            self.assertEqual(len(args[0]["benchmarks"]), 1)

    def test_fix_post(self):
        """Test POST /api/troubleshoot/fix endpoint."""
        self.handler.path = "/api/troubleshoot/fix"
        self.handler.headers = {"Content-Length": "38"}
        self.handler.rfile = unittest.mock.mock_open(read_data=b'{"fix_type": "reset_audio_defaults"}')()
        with patch("voicefi.troubleshoot.AudioTroubleshooter.apply_fix", return_value={"success": True, "message": "Reset done"}):
            self.handler.do_POST()
            self.handler._send_json.assert_called_once()
            args, _ = self.handler._send_json.call_args
            self.assertTrue(args[0]["success"])


if __name__ == "__main__":
    unittest.main()
