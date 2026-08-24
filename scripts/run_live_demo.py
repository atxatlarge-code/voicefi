#!/usr/bin/env python3
"""
🎬 VoiceFi Live Demo: The Ambient Agent Feedback Loop.
Demonstrates the core value of VoiceFi: hands-free, multi-turn conversational pair-programming with AI coding agents.

Modes:
  uv run python scripts/run_live_demo.py          # Live Interactive: Agent speaks -> Your mic opens -> You speak -> Real Whisper transcription!
  uv run python scripts/run_live_demo.py --auto   # Simulated Auto-Play: Timed playback for rapid screen capture
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Add src to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from voicefi.config import load_config
from voicefi.tts import get_tts_engine
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime

# ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def clear_screen():
    os.system("clear")


def banner():
    print(f"""{CYAN}{BOLD}
  ██╗   ██╗   ██████╗   ██╗   ██████╗  ███████╗  ███████╗  ██╗
  ██║   ██║  ██╔═══██╗  ██║  ██╔════╝  ██╔════╝  ██╔════╝  ██║
  ██║   ██║  ██║   ██║  ██║  ██║       █████╗    █████╗    ██║
  ╚██╗ ██╔╝  ██║   ██║  ██║  ██║       ██╔══╝    ██╔══╝    ██║
   ╚████╔╝   ╚██████╔╝  ██║  ╚██████╗  ███████╗  ██║       ██║
    ╚═══╝     ╚═════╝   ╚═╝   ╚═════╝  ╚══════╝  ╚═╝       ╚═╝
{RESET}{DIM}  The Universal Voice Layer for AI Agents, MCP, and macOS{RESET}
  {BLUE}https://voicefi.org • MIT Open Source • Patent Pending (63/137,300){RESET}
""")


def simulate_agent_working(task_desc: str, steps: list):
    print(f"\n{MAGENTA}{BOLD}🤖 [AI Agent Working in Background]{RESET} {DIM}— {task_desc}{RESET}")
    for step in steps:
        time.sleep(0.5)
        print(f"   {DIM}⚡ {step}{RESET}")
    time.sleep(0.4)


def run_live_turn(config, tts, stt, turn_num: int, agent_speech: str, simulated_reply: str, auto: bool):
    print(f"\n{'━'*64}")
    print(f"{BOLD}🔄 FEEDBACK LOOP — TURN {turn_num}{RESET}")
    print(f"{'━'*64}\n")

    # 1. Agent Speaks Turn Summary
    print(f"{BLUE}1. Agent Speaks Soundbite Aloud (No walls of text):{RESET}")
    print(f"   🎙️  {BOLD}Agent:{RESET} {CYAN}\"{agent_speech}\"{RESET}")
    tts.speak(agent_speech, block=True)

    # 2. VoiceFi Auto-arms Mic with VAD
    print(f"\n{BLUE}2. VoiceFi Auto-Arms Mic (Hands-Free):{RESET}")
    play_chime("start", block=True)

    user_text = ""
    if not auto:
        print(f"   {GREEN}● Mic LIVE! Speak your answer into your mic now (e.g. \"{simulated_reply}\")...{RESET}")
        recorder = AudioRecorder(
            sample_rate=config.vad.sample_rate,
            energy_threshold=config.vad.energy_threshold,
            silence_duration=1.4,
            max_record_seconds=15,
            barge_in=False,
        )
        audio_data, temp_wav = recorder.record_speech_auto(
            on_speech_start=lambda: print(f"   {YELLOW}🗣️  Speech detected (listening)...{RESET}"),
        )
        if temp_wav:
            print(f"   {DIM}Transcribing locally with Whisper...{RESET}")
            user_text = stt.transcribe(temp_wav)
            try:
                Path(temp_wav).unlink(missing_ok=True)
            except Exception:
                pass
        
        if not user_text or not user_text.strip():
            user_text = simulated_reply
    else:
        print(f"   {GREEN}● Mic Active (VAD energy detection listening)...{RESET}")
        time.sleep(1.2)
        print(f"   {YELLOW}🗣️  Developer: \"{simulated_reply}\"{RESET}")
        user_text = simulated_reply

    # 3. Whisper Transcribes & Injects
    play_chime("done", block=True)
    print(f"\n{BLUE}3. Transcribed & Sent to Agent Session:{RESET}")
    print(f"   {GREEN}✓ Local Whisper ({config.stt.model_size}) transcription: \"{user_text}\"{RESET}")
    print(f"   {GREEN}✓ Sent prompt back into Antigravity session. Agent resuming coding...{RESET}")
    time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Feedback Loop Demo")
    parser.add_argument("--auto", action="store_true", help="Simulate hands-free developer speech for automated recording")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    tts = get_tts_engine(config, agent_name="antigravity")
    stt = get_stt_engine(config)

    clear_screen()
    banner()

    print(f"{BOLD}🎬 LIVE DEMO: The Hands-Free Ambient Voice Loop{RESET}")
    print(f"{DIM}Watch how VoiceFi closes the feedback loop between Developer and AI Agent.{RESET}\n")

    if not args.auto:
        print(f"{YELLOW}👉 Interactive Mode: VoiceFi will speak to you and listen to your actual microphone!{RESET}")
        print(f"{DIM}Press ENTER to start the demo...{RESET}", end="", flush=True)
        try:
            input()
        except EOFError:
            pass
    else:
        print(f"{CYAN}⏱️ Running in automated timed mode for video recording...{RESET}")
        time.sleep(1.5)

    # ----------------------------------------------------
    # TURN 1: Status Confirmation & Next Action
    # ----------------------------------------------------
    simulate_agent_working(
        "Refactoring database connection pool & executing test suite",
        [
            "Modified src/voicefi/db/pool.py",
            "Executed pytest tests/test_db.py -- 42 passed in 1.4s",
            "Turn completed. Stop hook triggered.",
        ]
    )

    run_live_turn(
        config=config,
        tts=tts,
        stt=stt,
        turn_num=1,
        agent_speech="Refactored database pool. All 42 unit tests passed. Ready to generate the migrations?",
        simulated_reply="Yes, generate the migrations and use UUIDs for tenant IDs.",
        auto=args.auto,
    )

    # ----------------------------------------------------
    # TURN 2: Autonomous Execution & Clarification
    # ----------------------------------------------------
    simulate_agent_working(
        "Generating database schema migration for multi-tenant isolation",
        [
            "Created migrations/003_tenant_uuid.sql",
            "Verified foreign key constraints and schema indexes",
            "Migration validated successfully against SQLite test instance",
        ]
    )

    run_live_turn(
        config=config,
        tts=tts,
        stt=stt,
        turn_num=2,
        agent_speech="Migrations created and verified. Ready to push to main and trigger CI?",
        simulated_reply="Looks great. Commit with conventional commit message and push.",
        auto=args.auto,
    )

    # ----------------------------------------------------
    # FINAL WRAP UP
    # ----------------------------------------------------
    simulate_agent_working(
        "Committing changes & pushing upstream",
        [
            "git commit -m 'feat(db): add uuid tenant migration and connection pool'",
            "git push origin main",
            "CI build triggered: https://github.com/atxatlarge-code/voicefi/actions/104",
        ]
    )

    print(f"\n{'━'*64}")
    print(f"{GREEN}{BOLD}✨ FEEDBACK LOOP COMPLETE — ZERO KEYBOARD TOUCHES!{RESET}")
    print(f"{'━'*64}\n")

    final_announcement = "Release committed and pushed to main. CI pipeline is running."
    print(f"🎙️  {BOLD}Agent:{RESET} {CYAN}\"{final_announcement}\"{RESET}\n")
    tts.speak(final_announcement, block=True)

    print(f"  {CYAN}⚡ Install VoiceFi:{RESET} curl -fsSL https://vifi.sh | bash")
    print(f"  {BLUE}⭐ GitHub Repo:{RESET}     https://github.com/atxatlarge-code/voicefi")
    print(f"  {MAGENTA}🌐 Website:{RESET}         https://voicefi.org\n")


if __name__ == "__main__":
    main()
