#!/usr/bin/env python3
"""
VoiceFi ProActive Meeting Note Taker & Action Executor QA Simulation Tool.
Runs comprehensive end-to-end automated and interactive validation suites:
1. Multi-speaker conversation turn replay
2. Granola Markdown structure and metadata validation
3. Real-time action execution (Linear, Slack, Branch Scaffold, Research, Decisions)
4. Interactive Live Utterance QA Tester
5. MCP JSON-RPC Server tools validation
"""

import os
import sys
import time
import json
import tempfile
import argparse
import datetime
from pathlib import Path
from typing import List, Dict, Any

# Ensure local repo src is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from voicefi.config import load_config, VoiceFiConfig
from voicefi.integrations.meeting import (
    MeetingNoteTaker,
    MeetingSession,
    MeetingActionExecutor,
    ActionCategory,
    ActionStatus,
)
from voicefi.mcp_server import VoiceFiMCPServer


# ANSI Colors for Rich Terminal Output
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"


class MeetingQASuite:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.passed_checks = 0
        self.failed_checks = 0

    def log(self, text: str):
        if self.verbose:
            print(text)

    def assert_check(self, name: str, condition: bool, details: str = ""):
        if condition:
            self.passed_checks += 1
            print(f"  {GREEN}✔ [PASS]{RESET} {name} {f'({details})' if details else ''}")
        else:
            self.failed_checks += 1
            print(f"  {RED}✘ [FAIL]{RESET} {name} {f'- {details}' if details else ''}")

    def run_automated_simulation(self) -> bool:
        print(
            f"\n{BOLD}{CYAN}======================================================================{RESET}"
        )
        print(f"{BOLD}{CYAN} 🧪 VoiceFi Meeting Note Taker QA Suite: Automated Simulation {RESET}")
        print(
            f"{BOLD}{CYAN}======================================================================{RESET}\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = VoiceFiConfig()
            cfg.proactive.meeting_assistant.notes_dir = tmpdir
            cfg.proactive.meeting_assistant.auto_execute_actions = True

            taker = MeetingNoteTaker()
            taker._config = cfg

            title = "Architecture Review & Multi-Agent Dispatch"
            print(f"{BOLD}▶ Step 1: Starting Live Meeting Session...{RESET}")
            session = taker.start_session(title=title)
            self.assert_check("Session Started", session is not None and session.status == "active")
            self.assert_check(
                "Disk File Created", os.path.exists(session.markdown_path), session.markdown_path
            )

            print(
                f"\n{BOLD}▶ Step 2: Streaming Multi-Speaker Utterances & Verifying Actions...{RESET}"
            )
            script_turns = [
                {
                    "speaker": "Jake (Lead)",
                    "text": "Welcome team to our weekly engineering review and sprint planning session.",
                    "expected_action": False,
                    "expected_decision": False,
                },
                {
                    "speaker": "Sarah (Backend)",
                    "text": "We decided to migrate our session token cache from in-memory dictionary to Redis with a 24-hour TTL.",
                    "expected_action": False,
                    "expected_decision": True,
                },
                {
                    "speaker": "Jake (Lead)",
                    "text": "Create a linear ticket for updating the PostgreSQL schema migration scripts for user accounts",
                    "expected_action": True,
                    "expected_category": ActionCategory.LINEAR_TICKET,
                    "expected_decision": False,
                },
                {
                    "speaker": "Alex (DevOps)",
                    "text": "Post to #engineering-announcements that our staging deployment is complete and ready for testing",
                    "expected_action": True,
                    "expected_category": ActionCategory.SLACK_MESSAGE,
                    "expected_decision": False,
                },
                {
                    "speaker": "Sarah (Backend)",
                    "text": "Let's scaffold the Redis authentication middleware in an isolated branch",
                    "expected_action": True,
                    "expected_category": ActionCategory.SUBAGENT_SCAFFOLD,
                    "expected_decision": False,
                },
                {
                    "speaker": "Alex (Frontend)",
                    "text": "What is the docs for Cloudflare Workers KV TTL cache expiration limits?",
                    "expected_action": True,
                    "expected_category": ActionCategory.CODEBASE_RESEARCH,
                    "expected_decision": False,
                },
            ]

            for i, turn in enumerate(script_turns, 1):
                spk = turn["speaker"]
                txt = turn["text"]
                print(f'\n  {YELLOW}[Turn {i}]{RESET} {BOLD}{spk}:{RESET} "{txt}"')

                utt = taker.record_utterance(txt, speaker_name=spk)
                time.sleep(0.05)

                if turn.get("expected_decision"):
                    self.assert_check(
                        f"Turn {i} Decision Detected",
                        len(session.decisions) > 0,
                        session.decisions[-1].decision,
                    )
                elif turn.get("expected_action"):
                    self.assert_check(f"Turn {i} Action Detected", utt.is_actionable is True)
                    latest_act = session.action_items[-1]
                    self.assert_check(
                        f"Turn {i} Action Category Matched",
                        latest_act.category == turn["expected_category"],
                        f"{latest_act.category.value} -> {latest_act.result_summary}",
                    )
                    self.assert_check(
                        f"Turn {i} Auto-Execution Status",
                        latest_act.status == ActionStatus.COMPLETED,
                    )
                else:
                    self.assert_check(
                        f"Turn {i} General Discussion Handled", utt.is_actionable is False
                    )

            print(
                f"\n{BOLD}▶ Step 3: Validating Real-Time Disk Persistence & Granola Formatting...{RESET}"
            )
            self.assert_check("File Exists on Disk", os.path.isfile(session.markdown_path))
            with open(session.markdown_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            self.assert_check("Contains Title Header", f"# 👥 Meeting Notes: {title}" in md_content)
            self.assert_check(
                "Contains Executive Summary Section", "## ⚡ Executive Summary" in md_content
            )
            self.assert_check(
                "Contains Key Decisions Section",
                "## 🏗️ Architectural & Product Decisions" in md_content,
            )
            self.assert_check("Contains Redis Decision", "Redis" in md_content)
            self.assert_check(
                "Contains Actions Table",
                "## ⚡ Real-Time Actions Taken Along The Way" in md_content,
            )
            self.assert_check("Contains Linear Action", "LINEAR_TICKET" in md_content)
            self.assert_check("Contains Slack Action", "SLACK_MESSAGE" in md_content)
            self.assert_check("Contains Scaffold Action", "SUBAGENT_SCAFFOLD" in md_content)
            self.assert_check(
                "Contains Raw Transcript", "## 📝 Raw Conversation Transcript" in md_content
            )

            print(f"\n{BOLD}▶ Step 4: Finalizing & Stopping Session...{RESET}")
            final_session = taker.stop_session()
            self.assert_check("Session Finalized", final_session.status == "finalized")
            self.assert_check("Active Session Cleared", taker.active_session is None)

            print(f"\n{BOLD}▶ Step 5: Validating Session Listing & Retrieval...{RESET}")
            saved_list = taker.list_saved_sessions(directory=tmpdir)
            self.assert_check("Session Listed", len(saved_list) == 1, saved_list[0]["filename"])

            # Step 6: MCP Server Tool Validation
            print(f"\n{BOLD}▶ Step 6: Validating MCP JSON-RPC Tools...{RESET}")
            mcp = VoiceFiMCPServer()
            mcp_res_start = mcp.execute_tool(
                "voicefi_meeting_start",
                {"title": "MCP QA Validation", "output_path": os.path.join(tmpdir, "mcp_qa.md")},
            )
            self.assert_check("MCP voicefi_meeting_start", mcp_res_start.get("isError") is False)

            mcp_res_status = mcp.execute_tool("voicefi_meeting_status", {})
            self.assert_check("MCP voicefi_meeting_status", mcp_res_status.get("isError") is False)

            mcp_res_act = mcp.execute_tool(
                "voicefi_meeting_action",
                {
                    "action_type": "linear_ticket",
                    "title": "MCP QA Linear Ticket Verification",
                    "details": {"assignee": "Jake"},
                },
            )
            self.assert_check("MCP voicefi_meeting_action", mcp_res_act.get("isError") is False)

            mcp_res_stop = mcp.execute_tool("voicefi_meeting_stop", {})
            self.assert_check("MCP voicefi_meeting_stop", mcp_res_stop.get("isError") is False)

        print(f"\n{BOLD}{'=' * 70}{RESET}")
        total = self.passed_checks + self.failed_checks
        if self.failed_checks == 0:
            print(f"{BOLD}{GREEN}🎉 ALL {total} QA CHECKS PASSED PERFECTLY! (100% SUCCESS){RESET}")
        else:
            print(
                f"{BOLD}{RED}❌ QA RUN FINISHED WITH {self.failed_checks} / {total} FAILING CHECKS.{RESET}"
            )
        print(f"{BOLD}{'=' * 70}{RESET}\n")

        return self.failed_checks == 0

    def run_interactive_tester(self):
        """Interactive console where developer speaks or types phrases to test triage and real-time execution."""
        print(
            f"\n{BOLD}{CYAN}======================================================================{RESET}"
        )
        print(f"{BOLD}{CYAN} 🎙️ VoiceFi Meeting Note Taker: Interactive QA Tester {RESET}")
        print(
            f"{BOLD}{CYAN}======================================================================{RESET}"
        )
        print("Type any meeting utterance below to test classification and real-time execution.")
        print(
            f"Type {BOLD}'q'{RESET} or {BOLD}'exit'{RESET} to quit, or {BOLD}'show'{RESET} to view generated markdown.\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = VoiceFiConfig()
            cfg.proactive.meeting_assistant.notes_dir = tmpdir
            taker = MeetingNoteTaker()
            taker._config = cfg

            session = taker.start_session(title="Interactive QA Testing Session")
            print(f"🟢 Active Meeting Notes File: {session.markdown_path}\n")

            while True:
                try:
                    user_input = input(f"{BOLD}{BLUE}Speak/Type Utterance > {RESET}").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("q", "exit", "quit"):
                    break
                if user_input.lower() == "show":
                    with open(session.markdown_path, "r", encoding="utf-8") as f:
                        print(f"\n{f.read()}\n")
                    continue

                utt = taker.record_utterance(user_input, speaker_name="Tester")
                print(f"  📝 Recorded at [{utt.timestamp_str}]")
                if session.decisions and session.decisions[-1].decision in user_input:
                    print(f"  🏛️  {GREEN}Decision Logged:{RESET} {session.decisions[-1].decision}")
                if utt.is_actionable and session.action_items:
                    latest = session.action_items[-1]
                    print(
                        f"  ⚡ {GREEN}Action Triggered [{latest.category.value}]:{RESET} {latest.title}"
                    )
                    print(f"     👉 Result: {latest.result_summary}")
                elif not utt.is_actionable:
                    print("  💬 General Discussion (No immediate action trigger)")
                print()

            final_session = taker.stop_session()
            print(f"\n🏁 Session stopped. Final notes written to: {final_session.markdown_path}\n")


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Meeting Note Taker QA Tool")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Launch interactive utterance tester"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", default=True, help="Verbose logging"
    )
    args = parser.parse_args()

    suite = MeetingQASuite(verbose=args.verbose)
    if args.interactive:
        suite.run_interactive_tester()
    else:
        success = suite.run_automated_simulation()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
