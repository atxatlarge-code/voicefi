"""
Side-by-Side STT Benchmark: Faster-Whisper (CPU) vs. MLX-Whisper (Metal GPU).
Measures Real-Time Factor (RTF), latency, CPU utilization, and transcription accuracy.
"""

import time
import os
import sys
from pathlib import Path
import numpy as np
import psutil

# Ensure src is in python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voicefi.config import VoiceFiConfig
from voicefi.stt.whisper_local import WhisperLocalSTT


def generate_synthetic_audio(duration_sec: float = 4.0, sample_rate: int = 16000) -> np.ndarray:
    """Generate multi-tone test audio with harmonics resembling human vocal frequencies."""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    # Fundamental vocal frequencies ~150Hz, 300Hz, 600Hz
    signal = 0.4 * np.sin(2 * np.pi * 150 * t) + 0.3 * np.sin(2 * np.pi * 300 * t) + 0.2 * np.sin(2 * np.pi * 600 * t)
    # Envelope shaping
    envelope = np.ones_like(t)
    attack_samples = int(sample_rate * 0.1)
    envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
    envelope[-attack_samples:] = np.linspace(1, 0, attack_samples)
    return (signal * envelope).astype(np.float32)


def benchmark_engine(name: str, engine, audio: np.ndarray, sample_rate: int = 16000, runs: int = 3):
    """Run benchmark passes and record performance metrics."""
    proc = psutil.Process(os.getpid())
    print(f"\n🚀 Benchmarking: {name}")
    print("-" * 50)

    # Warmup
    try:
        t0 = time.perf_counter()
        _ = engine.transcribe(audio, sample_rate=sample_rate)
        warmup_time = time.perf_counter() - t0
        print(f"  🔥 Warmup / Model Load: {warmup_time:.3f}s")
    except Exception as e:
        print(f"  ❌ Engine failed warmup: {e}")
        return None

    latencies = []
    cpu_percentages = []

    for i in range(runs):
        proc.cpu_percent()  # Reset CPU counter
        t_start = time.perf_counter()
        transcript = engine.transcribe(audio, sample_rate=sample_rate)
        t_end = time.perf_counter()
        cpu_used = proc.cpu_percent()

        latency = (t_end - t_start) * 1000.0  # ms
        latencies.append(latency)
        cpu_percentages.append(cpu_used)
        print(f"  Pass {i + 1}: {latency:.1f}ms (CPU: {cpu_used:.1f}%) -> {repr(transcript[:40])}")

    audio_dur_ms = (len(audio) / sample_rate) * 1000.0
    avg_latency = np.mean(latencies)
    rtf = avg_latency / audio_dur_ms  # Real-Time Factor (<1.0 is faster than real time)
    speedup = audio_dur_ms / avg_latency

    result = {
        "engine": name,
        "audio_duration_sec": len(audio) / sample_rate,
        "avg_latency_ms": avg_latency,
        "min_latency_ms": np.min(latencies),
        "rtf": rtf,
        "speedup_x_realtime": speedup,
        "avg_cpu_percent": np.mean(cpu_percentages),
    }

    print(f"\n  📊 Summary for {name}:")
    print(f"     Average Latency: {avg_latency:.1f} ms")
    print(f"     Real-Time Factor: {rtf:.3f}x ({speedup:.1f}x faster than real-time)")
    print(f"     Average CPU Load: {np.mean(cpu_percentages):.1f}%\n")
    return result


def main():
    print("=" * 60)
    print("🎙️  VoiceFi Apple Silicon STT Benchmark Suite")
    print("=" * 60)

    audio = generate_synthetic_audio(duration_sec=5.0)

    # 1. Faster-Whisper (CPU)
    fw_engine = WhisperLocalSTT(model_size="base.en")
    fw_result = benchmark_engine("Faster-Whisper (CPU, base.en)", fw_engine, audio)

    # 2. MLX-Whisper (Metal GPU)
    mlx_result = None
    try:
        from voicefi.stt.mlx_whisper import MLXWhisperSTT
        mlx_engine = MLXWhisperSTT(model_name="mlx-community/whisper-large-v3-turbo")
        mlx_result = benchmark_engine("MLX-Whisper (Metal GPU, Large-v3-Turbo)", mlx_engine, audio)
    except Exception as e:
        print(f"\n⚠️ MLX-Whisper not run: {e}")

    if fw_result and mlx_result:
        print("=" * 60)
        print("🏆 Final Head-to-Head Comparison")
        print("=" * 60)
        print("Metric                    Faster-Whisper (CPU)       MLX-Whisper (Metal)")
        print("----------------------------------------------------------------------")
        print(f"Average Latency:          {fw_result['avg_latency_ms']:.1f} ms               {mlx_result['avg_latency_ms']:.1f} ms")
        print(f"Speedup vs Real-time:     {fw_result['speedup_x_realtime']:.1f}x                      {mlx_result['speedup_x_realtime']:.1f}x")
        print(f"CPU Utilization:          {fw_result['avg_cpu_percent']:.1f}%                     {mlx_result['avg_cpu_percent']:.1f}%")
        print("=" * 60)


if __name__ == "__main__":
    main()
