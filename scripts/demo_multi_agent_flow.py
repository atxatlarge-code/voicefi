"""
Demonstration script of the Voicegency Multi-Agent Voice Workflow.
Plays a live turn-by-turn handoff across Main Planner, Researcher, and Debugger subagents.
"""

import time
import sys
from pathlib import Path

# Add src to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from voicegency.config import load_config
from voicegency.tts import get_tts_engine
from voicegency.tts.base import speech_turn_lock


def run_multi_agent_demo():
    config = load_config()

    dialogue = [
        (
            "antigravity",
            "Christopher (Main Planner)",
            "Starting the deployment workflow. Spawning the Researcher and QA subagents in the background now.",
        ),
        (
            "researcher",
            "Sonia (Researcher Subagent)",
            "Research complete. I surveyed the repository and verified all API contract endpoints.",
        ),
        (
            "debugger",
            "Aria (Debugger / QA Subagent)",
            "Test suite executed! All 29 unit tests and performance benchmarks are green.",
        ),
        (
            "antigravity",
            "Christopher (Main Planner)",
            "All subagent tasks finished. We are ready to ship the release whenever you are, Jake.",
        ),
    ]

    print("\n🎭 === Voicegency Multi-Agent Swarm Simulation ===\n")
    with speech_turn_lock():
        for role, label, text in dialogue:
            print(f"🎙️ [{label}]")
            print(f"   \"{text}\"\n")
            tts = get_tts_engine(config, agent_name=role)
            tts.speak(text, block=True)
            time.sleep(0.4)

    print("✨ Multi-agent simulation complete!\n")


if __name__ == "__main__":
    run_multi_agent_demo()
