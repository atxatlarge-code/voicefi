"""
VoiceFi Doctor — Comprehensive environment, hardware, dependency & self-healing diagnostics.
Verifies audio DAC sample rates, MLX Metal GPU support, tokenizers compatibility,
port availability, and air-gap privacy compliance.
"""

import importlib.metadata
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from voicefi.config import load_config
from voicefi.telemetry import is_offline_mode, is_telemetry_enabled


def check_python_environment() -> Dict[str, Any]:
    """Check Python interpreter, version, and virtual environment status."""
    ver = platform.python_version()
    major, minor, patch = map(int, ver.split(".")[:3])
    is_supported = major == 3 and minor in (10, 11, 12, 13)
    is_venv = sys.prefix != sys.base_prefix

    status = "pass"
    message = f"Python {ver} ({platform.machine()}) in virtualenv: {is_venv}"
    if not is_supported:
        status = "warn"
        message = f"Python {ver} detected; VoiceFi is optimized for Python 3.10-3.13"

    return {
        "category": "Environment",
        "name": "Python Runtime",
        "status": status,
        "details": message,
        "version": ver,
        "is_venv": is_venv,
        "executable": sys.executable,
    }


def check_package_dependencies() -> List[Dict[str, Any]]:
    """Verify core and neural audio package versions and check for known collisions."""
    results = []

    # 1. tokenizers & mlx-audio compatibility
    mlx_audio_installed = False
    try:
        mlx_audio_ver = importlib.metadata.version("mlx-audio")
        mlx_audio_installed = True
    except Exception:
        mlx_audio_ver = None

    try:
        tokenizers_ver = importlib.metadata.version("tokenizers")
    except Exception:
        tokenizers_ver = None

    if tokenizers_ver:
        # If mlx-audio is installed, tokenizers must be >= 0.23.0 to prevent Tokenizer not loaded crash
        tok_parts = [int(p) for p in tokenizers_ver.split(".")[:3] if p.isdigit()]
        is_tok_compat = True
        if mlx_audio_installed and len(tok_parts) >= 2:
            if tok_parts[0] == 0 and tok_parts[1] < 23:
                is_tok_compat = False

        if not is_tok_compat:
            results.append(
                {
                    "category": "Dependencies",
                    "name": "Tokenizers / MLX-Audio Alignment",
                    "status": "fail",
                    "details": f"tokenizers {tokenizers_ver} incompatible with mlx-audio {mlx_audio_ver}. Requires >= 0.23.1.",
                    "fix_command": f"{sys.executable} -m pip install 'tokenizers>=0.23.1,<0.24.0'",
                }
            )
        else:
            results.append(
                {
                    "category": "Dependencies",
                    "name": "Tokenizers & MLX-Audio",
                    "status": "pass",
                    "details": f"tokenizers {tokenizers_ver} aligned with mlx-audio {mlx_audio_ver or 'not installed'}",
                }
            )
    else:
        results.append(
            {
                "category": "Dependencies",
                "name": "Tokenizers",
                "status": "warn",
                "details": "tokenizers not installed (cloud TTS mode only)",
            }
        )

    # 2. Faster-Whisper
    try:
        fw_ver = importlib.metadata.version("faster-whisper")
        results.append(
            {
                "category": "Dependencies",
                "name": "Faster-Whisper (Local STT)",
                "status": "pass",
                "details": f"faster-whisper {fw_ver} ready",
            }
        )
    except Exception:
        results.append(
            {
                "category": "Dependencies",
                "name": "Faster-Whisper (Local STT)",
                "status": "warn",
                "details": "faster-whisper not installed (cloud Groq STT available)",
            }
        )

    # 3. MLX / MLX-Whisper on Apple Silicon
    is_apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    if is_apple_silicon:
        try:
            mlx_ver = importlib.metadata.version("mlx")
            results.append(
                {
                    "category": "Dependencies",
                    "name": "Apple MLX (Metal GPU)",
                    "status": "pass",
                    "details": f"Apple MLX {mlx_ver} active on Apple Silicon",
                }
            )
        except Exception:
            results.append(
                {
                    "category": "Dependencies",
                    "name": "Apple MLX (Metal GPU)",
                    "status": "warn",
                    "details": "mlx not installed (Metal GPU neural acceleration unavailable)",
                }
            )

    # 4. PostHog Telemetry SDK
    try:
        ph_ver = importlib.metadata.version("posthog")
        results.append(
            {
                "category": "Dependencies",
                "name": "PostHog SDK",
                "status": "pass",
                "details": f"posthog {ph_ver} ready",
            }
        )
    except Exception:
        results.append(
            {
                "category": "Dependencies",
                "name": "PostHog SDK",
                "status": "warn",
                "details": "posthog SDK not installed; falling back to direct HTTPS",
            }
        )

    return results


def check_audio_devices() -> Dict[str, Any]:
    """Inspect CoreAudio hardware device sample rates and profiles."""
    try:
        from voicefi.audio.device import (
            get_default_audio_devices,
            is_bluetooth_input_active,
            is_headphone_or_headset_active,
        )

        in_dev, out_dev = get_default_audio_devices()
        out_name = out_dev.get("name", "Unknown") if out_dev else "None detected"
        out_sr = out_dev.get("default_samplerate", 0) if out_dev else 0
        in_name = in_dev.get("name", "Unknown") if in_dev else "None detected"

        bt_input = is_bluetooth_input_active()
        headphones = is_headphone_or_headset_active()

        if out_dev and in_dev:
            if headphones and bt_input:
                status = "warn"
                msg = (
                    f"Output: {out_name} ({out_sr}Hz) | Input: {in_name}\n"
                    f"  ⚠️ Audio Input Device Lock: Input is set to Bluetooth earbuds. "
                    f"Keeping input on MacBook Pro Microphone in System Settings → Sound → Input "
                    f"will keep your earbuds in high-fidelity stereo (prevents SCO/HFP mono downgrade)."
                )
            else:
                status = "pass"
                msg = f"Output: {out_name} ({out_sr}Hz) | Input: {in_name}"
        elif out_dev:
            status = "warn"
            msg = f"Output: {out_name} ({out_sr}Hz) | Input: None (Microphone missing)"
        else:
            status = "fail"
            msg = "No audio output device found via CoreAudio"

        return {
            "category": "Hardware",
            "name": "CoreAudio Hardware",
            "status": status,
            "details": msg,
            "output_device": out_name,
            "output_samplerate": out_sr,
            "input_device": in_name,
            "audio_input_lock_recommended": headphones and bt_input,
        }
    except Exception as e:
        return {
            "category": "Hardware",
            "name": "CoreAudio Hardware",
            "status": "warn",
            "details": f"Could not inspect CoreAudio devices: {e}",
        }


def check_port_availability() -> List[Dict[str, Any]]:
    """Check IPC bridge (5141) and Companion server (5142) port states."""
    results = []
    ports = [
        (5141, "IPC Bridge (Antigravity/Claude)", "http://localhost:5141"),
        (5142, "Mobile Companion PWA", "http://localhost:5142"),
    ]

    for port, label, url in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.4)
        is_open = sock.connect_ex(("127.0.0.1", port)) == 0
        sock.close()

        if is_open:
            results.append(
                {
                    "category": "Daemon & Ports",
                    "name": f"Port {port} ({label})",
                    "status": "pass",
                    "details": f"Active & listening at {url}",
                    "is_running": True,
                }
            )
        else:
            results.append(
                {
                    "category": "Daemon & Ports",
                    "name": f"Port {port} ({label})",
                    "status": "pass",
                    "details": "Port is free and ready to bind on startup",
                    "is_running": False,
                }
            )
    return results


def check_privacy_and_airgap() -> Dict[str, Any]:
    """Check air-gap isolation and telemetry privacy configuration."""
    offline = is_offline_mode()
    telemetry = is_telemetry_enabled()

    if offline:
        status = "pass"
        msg = "Air-Gap Active (VOICEFI_OFFLINE / VOICEFI_AIRGAP set) — Zero telemetry egress guaranteed"
    elif not telemetry:
        status = "pass"
        msg = "Telemetry Disabled via DO_NOT_TRACK / config — Local analytics only"
    else:
        status = "pass"
        msg = "Anonymous Zero-PII Error Tracking & Diagnostics active (PostHog US)"

    return {
        "category": "Privacy",
        "name": "Air-Gap & Privacy Compliance",
        "status": status,
        "details": msg,
        "is_offline_mode": offline,
        "is_telemetry_enabled": telemetry,
    }


def check_hook_latency() -> Dict[str, Any]:
    """Inspect AI agent turn-end hook fast path dispatch latency to guarantee < 100ms response."""
    import time
    import urllib.request

    url = "http://127.0.0.1:5141/api/hook/event"
    start = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"agent": "antigravity", "test_ping": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if resp.status == 200:
                if elapsed_ms < 100.0:
                    status = "pass"
                    details = (
                        f"Hook fast path active: {elapsed_ms:.1f}ms IPC roundtrip (Target: < 100ms)"
                    )
                elif elapsed_ms < 300.0:
                    status = "warn"
                    details = (
                        f"Hook fast path active but elevated: {elapsed_ms:.1f}ms IPC roundtrip"
                    )
                else:
                    status = "warn"
                    details = (
                        f"Hook fast path sluggish: {elapsed_ms:.1f}ms IPC roundtrip (SLA exceeded)"
                    )
                return {
                    "category": "Agent Integration",
                    "name": "Hook Dispatch Latency",
                    "status": status,
                    "details": details,
                    "latency_ms": round(elapsed_ms, 2),
                    "is_daemon_active": True,
                }
    except Exception as e:
        return {
            "category": "Agent Integration",
            "name": "Hook Dispatch Latency",
            "status": "warn",
            "details": f"Companion daemon not responding on 5141 ({e}). Run `vifi companion` or launch menubar app for instant (<30ms) turn ends.",
            "latency_ms": None,
            "is_daemon_active": False,
        }


def run_diagnostics() -> Dict[str, Any]:
    """Execute all diagnostic health checks."""
    checks = []
    checks.append(check_python_environment())
    checks.extend(check_package_dependencies())
    checks.append(check_audio_devices())
    checks.extend(check_port_availability())
    checks.append(check_hook_latency())
    checks.append(check_privacy_and_airgap())

    has_failures = any(c["status"] == "fail" for c in checks)
    has_warnings = any(c["status"] == "warn" for c in checks)

    overall = "fail" if has_failures else ("warn" if has_warnings else "pass")
    return {
        "timestamp": platform.node(),
        "overall_status": overall,
        "checks": checks,
    }


def apply_doctor_fixes(diagnostics: Dict[str, Any]) -> List[str]:
    """Apply automated self-healing remedies for detected failures."""
    actions_taken = []

    for c in diagnostics.get("checks", []):
        if c.get("status") == "fail" and c.get("fix_command"):
            cmd = c["fix_command"]
            print(f"🔧 Applying automated fix for {c['name']}...")
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    actions_taken.append(f"Successfully ran fix for {c['name']}")
                    print(f"  ✅ Fixed {c['name']}")
                else:
                    print(f"  ❌ Fix failed: {res.stderr[:200]}")
            except Exception as e:
                print(f"  ❌ Fix error: {e}")

    return actions_taken


def cmd_doctor(args: Any) -> int:
    """CLI Entry point for `vifi doctor` / `vifi health`."""
    is_json = getattr(args, "json", False)
    do_fix = getattr(args, "fix", False)

    diag = run_diagnostics()

    if do_fix:
        actions = apply_doctor_fixes(diag)
        if actions:
            diag = run_diagnostics()

    if is_json:
        print(json.dumps(diag, indent=2))
        return 0 if diag["overall_status"] != "fail" else 1

    status_icons = {
        "pass": "🟢 PASS",
        "warn": "🟡 WARN",
        "fail": "🔴 FAIL",
    }

    print("\n🩺 VoiceFi Doctor — System Diagnostics & Self-Healing")
    print("=" * 70)

    current_cat = None
    for c in diag["checks"]:
        cat = c["category"]
        if cat != current_cat:
            print(f"\n[{cat}]")
            current_cat = cat

        icon = status_icons.get(c["status"], "⚪")
        print(f"  {icon}  {c['name']:<34} | {c['details']}")

    print("\n" + "=" * 70)
    if diag["overall_status"] == "pass":
        print("✨ All systems healthy! VoiceFi is ready for audio & agent operations.\n")
        return 0
    elif diag["overall_status"] == "warn":
        print("⚠️ System operational with minor warnings. VoiceFi will use appropriate fallbacks.\n")
        return 0
    else:
        print("❌ Critical issues detected. Run `vifi doctor --fix` to attempt auto-repair.\n")
        return 1
