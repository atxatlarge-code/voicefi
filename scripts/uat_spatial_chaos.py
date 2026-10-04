#!/usr/bin/env python3
"""
scripts/uat_spatial_chaos.py
VoiceFi Adversarial UAT & Chaos "Break-It" Suite for Spatial Audio.

Tests the resilience of the spatial stereo engine against:
1. Malicious / Hostile Pan Coordinates (NaN, Inf, Overflow, Non-numeric)
2. Pathological Audio Buffers (Zero-length, NaNs, Infs, Lists, Int32)
3. 32-Thread Concurrency Dogpile (Race conditions & contention)
4. CoreAudio Route Switching & Driver Exception Chaos
5. Constant Acoustic Power Invariant Maintenance
"""

import concurrent.futures
import math
import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voicefi.audio.spatial import (
    pan_audio,
    get_agent_pan,
    adapt_pan_for_active_device,
    create_spatial_tone,
)


class SpatialUATTester:
    def __init__(self):
        self.results = []

    def record(self, test_name: str, passed: bool, details: str, duration_s: float):
        status = "✅ SURVIVED" if passed else "❌ BROKEN"
        print(f"{status} | {test_name:<38} ({duration_s*1000:6.2f}ms) - {details}")
        self.results.append({
            "test": test_name,
            "passed": passed,
            "details": details,
            "duration_ms": round(duration_s * 1000, 2),
        })

    def run_all(self):
        print("\n" + "=" * 70)
        print("💥 VoiceFi Spatial Audio Adversarial UAT & Break-It Suite")
        print("=" * 70)

        self.test_hostile_pan_fuzzing()
        self.test_pathological_audio_buffers()
        self.test_extreme_buffer_stress()
        self.test_concurrency_dogpile_32_threads()
        self.test_coreaudio_driver_chaos()
        self.test_power_conservation_invariant()

        print("-" * 70)
        passed_count = sum(1 for r in self.results if r["passed"])
        total_count = len(self.results)
        pct = (passed_count / total_count) * 100
        print(f"Overall Result: {passed_count}/{total_count} chaos tests survived ({pct:.1f}% resilient)")
        print("=" * 70 + "\n")
        return passed_count == total_count

    # 1. Hostile Pan Fuzzing
    def test_hostile_pan_fuzzing(self):
        t0 = time.time()
        fuzz_cases = [
            float("nan"),
            float("inf"),
            float("-inf"),
            1e12,
            -1e12,
            None,
            "hard_left",
            [0.5],
            {"pan": 0.5},
        ]
        audio = np.ones(100, dtype=np.float32)
        try:
            for val in fuzz_cases:
                res = pan_audio(audio, pan=val)
                assert res.shape == (100, 2), f"Failed shape for pan={val}"
                assert not np.isnan(res).any(), f"NaN leaked for pan={val}"
                assert not np.isinf(res).any(), f"Inf leaked for pan={val}"
            self.record(
                "Hostile Pan Fuzzing",
                True,
                "Cleanly absorbed NaN, Inf, overflow (1e12), None, and non-numeric inputs without raising exceptions.",
                time.time() - t0,
            )
        except Exception as e:
            self.record("Hostile Pan Fuzzing", False, f"Exception raised: {e}", time.time() - t0)

    # 2. Pathological Audio Buffers
    def test_pathological_audio_buffers(self):
        t0 = time.time()
        try:
            # Zero-length
            empty = np.array([], dtype=np.float32)
            res_empty = pan_audio(empty, pan=-0.5)
            assert res_empty.shape == (0, 2)

            # Audio containing NaNs and Infs
            dirty = np.array([0.5, float("nan"), -0.5, float("inf"), float("-inf")], dtype=np.float32)
            res_dirty = pan_audio(dirty, pan=0.5)
            assert not np.isnan(res_dirty).any()
            assert not np.isinf(res_dirty).any()

            # Python list input (non-numpy)
            py_list = [0.1, -0.2, 0.3]
            res_list = pan_audio(py_list, pan=0.0)
            assert isinstance(res_list, np.ndarray)
            assert res_list.shape == (3, 2)

            # Int32 input
            i32_arr = np.array([1000000, -1000000], dtype=np.int32)
            res_i32 = pan_audio(i32_arr, pan=0.2)
            assert res_i32.dtype == np.float32

            self.record(
                "Pathological Audio Buffers",
                True,
                "Sanitized 0-length buffers, raw python lists, int32 arrays, and nan/inf samples safely.",
                time.time() - t0,
            )
        except Exception as e:
            self.record("Pathological Audio Buffers", False, f"Failed on dirty audio: {e}", time.time() - t0)

    # 3. Extreme Buffer Stress
    def test_extreme_buffer_stress(self):
        t0 = time.time()
        try:
            # 5 million samples (~208 seconds of 24kHz audio)
            huge_mono = np.sin(np.linspace(0, 1000, 5_000_000, dtype=np.float32))
            res = pan_audio(huge_mono, pan=-0.35)
            assert res.shape == (5_000_000, 2)
            assert res.dtype == np.float32
            dur = time.time() - t0
            self.record(
                "5M Sample Buffer Stress (~208s audio)",
                True,
                f"Processed 5,000,000 samples into stereo in {dur*1000:.1f}ms without memory exhaustion.",
                dur,
            )
        except Exception as e:
            self.record("5M Sample Buffer Stress", False, f"Memory error: {e}", time.time() - t0)

    # 4. Concurrency Dogpile (32 Workers)
    def test_concurrency_dogpile_32_threads(self):
        t0 = time.time()
        num_workers = 32
        iterations_per_worker = 100

        def worker_task(worker_id):
            np.random.seed(worker_id)
            for _ in range(iterations_per_worker):
                pan = np.random.uniform(-1.5, 1.5)
                audio = np.random.randn(256).astype(np.float32)
                res = pan_audio(audio, pan=pan)
                assert res.shape == (256, 2)
                tone = create_spatial_tone(freq=440.0 + worker_id, duration=0.01, pan=pan)
                assert tone.ndim == 2
            return True

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [executor.submit(worker_task, i) for i in range(num_workers)]
                for f in concurrent.futures.as_completed(futures):
                    assert f.result() is True

            self.record(
                "Concurrency Dogpile (32 Threads)",
                True,
                f"32 concurrent workers completed {num_workers * iterations_per_worker} spatial DSP turns with zero race conditions.",
                time.time() - t0,
            )
        except Exception as e:
            self.record("Concurrency Dogpile (32 Threads)", False, f"Contention deadlock/failure: {e}", time.time() - t0)

    # 5. CoreAudio Driver Chaos
    def test_coreaudio_driver_chaos(self):
        t0 = time.time()
        try:
            # Simulate CoreAudio daemon crash / device query explosion
            with patch("voicefi.audio.device.is_headphone_or_headset_active", side_effect=RuntimeError("HAL server died")):
                res_pan = adapt_pan_for_active_device(-0.6)
                assert res_pan == -0.6  # Fails open gracefully

            with patch("voicefi.audio.device.is_headphone_or_headset_active", side_effect=OSError("CoreAudio device not found")):
                agent_pan = get_agent_pan("antigravity", adapt_for_device=True)
                assert agent_pan < 0.0  # Still resolves Antigravity to left channel

            self.record(
                "CoreAudio Driver Chaos",
                True,
                "Gracefully survived simulated CoreAudio HAL crashes and device dropouts (fail-open architecture).",
                time.time() - t0,
            )
        except Exception as e:
            self.record("CoreAudio Driver Chaos", False, f"Failed on driver chaos: {e}", time.time() - t0)

    # 6. Power Conservation Invariant
    def test_power_conservation_invariant(self):
        t0 = time.time()
        try:
            # Across 200 random pans in [-1.0, 1.0], verify L^2 + R^2 == 1.0 exactly
            pans = np.linspace(-1.0, 1.0, 200)
            sample = np.ones(1, dtype=np.float32)
            max_dev = 0.0

            for p in pans:
                stereo = pan_audio(sample, pan=p)
                L = stereo[0, 0]
                R = stereo[0, 1]
                power = L**2 + R**2
                dev = abs(power - 1.0)
                if dev > max_dev:
                    max_dev = dev
                assert np.isclose(power, 1.0, atol=1e-5)

            self.record(
                "Acoustic Power Invariant (L² + R² = 1)",
                True,
                f"Verified across 200 pan coordinates. Maximum power deviation was {max_dev:.2e} (100% compliant).",
                time.time() - t0,
            )
        except Exception as e:
            self.record("Acoustic Power Invariant", False, f"Power conservation broken: {e}", time.time() - t0)


if __name__ == "__main__":
    tester = SpatialUATTester()
    success = tester.run_all()
    sys.exit(0 if success else 1)
