"""
Unit tests for ProActive Meeting Note Taker and Real-Time Action Executor Engine.
"""

import os
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from voicefi.config import VoiceFiConfig, ProActiveMeetingAssistantConfig
from voicefi.integrations.meeting import (
    MeetingSession,
    MeetingUtterance,
    MeetingDecision,
    MeetingActionItem,
    ActionCategory,
    ActionStatus,
    MeetingActionExecutor,
    MeetingNoteTaker,
)
from voicefi.mcp_server import VoiceFiMCPServer


def test_meeting_session_granola_markdown():
    session = MeetingSession(
        session_id="2026-08-29_18-00-00",
        title="Weekly Architectural Review & Sprint Triage",
        started_at=1788020000.0,
        ended_at=1788023600.0,
        status="finalized",
    )
    session.topics = ["Redis Token Cache Migration", "Linear Workflow Integration"]
    session.decisions.append(
        MeetingDecision(
            topic="Redis Caching",
            decision="Adopt Redis for multi-worker token caching",
            rationale="Sub-millisecond token lookup latency",
            timestamp_str="18:15:00",
        )
    )
    session.action_items.append(
        MeetingActionItem(
            id="act_1",
            raw_utterance="Create a linear ticket for auth token cache migration",
            title="Linear: Auth token cache migration",
            category=ActionCategory.LINEAR_TICKET,
            status=ActionStatus.COMPLETED,
            assignee="Jake",
            target_channel_or_branch="Linear Backlog",
            result_summary="Linear Issue #ENG-204 Created (Assigned to @Jake)",
        )
    )
    session.utterances.append(
        MeetingUtterance(
            timestamp_str="18:05:00",
            speaker="Jake",
            text="Let's start the review.",
        )
    )

    md = session.format_granola_markdown()
    assert "# 👥 Meeting Notes: Weekly Architectural Review & Sprint Triage" in md
    assert "## ⚡ Executive Summary" in md
    assert "## 🎯 Key Topics & Discussion Points" in md
    assert "Redis Token Cache Migration" in md
    assert "## 🏗️ Architectural & Product Decisions" in md
    assert "Adopt Redis for multi-worker token caching" in md
    assert "## ⚡ Real-Time Actions Taken Along The Way" in md
    assert "Linear Issue #ENG-204 Created" in md
    assert "## 📝 Raw Conversation Transcript" in md
    assert "Let's start the review." in md


def test_action_executor_parse_utterance():
    # Linear intent
    res1 = MeetingActionExecutor.parse_utterance("Create a linear ticket for database indexing optimization")
    assert res1["is_action"] is True
    assert res1["action_item"].category == ActionCategory.LINEAR_TICKET
    assert "Database indexing optimization" in res1["action_item"].title

    # Slack intent
    res2 = MeetingActionExecutor.parse_utterance("Post to dev-announcements that auth migration is live")
    assert res2["is_action"] is True
    assert res2["action_item"].category == ActionCategory.SLACK_MESSAGE
    assert res2["action_item"].target_channel_or_branch == "#dev-announcements"

    # Branch scaffold intent
    res3 = MeetingActionExecutor.parse_utterance("Let's scaffold the webhook authentication middleware in an isolated branch")
    assert res3["is_action"] is True
    assert res3["action_item"].category == ActionCategory.SUBAGENT_SCAFFOLD
    assert "proactive/" in res3["action_item"].target_channel_or_branch

    # Research intent
    res4 = MeetingActionExecutor.parse_utterance("What is the docs for Cloudflare Workers KV TTL?")
    assert res4["is_action"] is True
    assert res4["action_item"].category == ActionCategory.CODEBASE_RESEARCH

    # Architectural Decision intent
    res5 = MeetingActionExecutor.parse_utterance("We decided to migrate our caching layer from in-memory to Redis")
    assert res5["is_decision"] is True
    assert "Migrate our caching layer" in res5["decision"].decision


def test_action_executor_execution():
    act = MeetingActionItem(
        id="act_test",
        raw_utterance="Create linear ticket for refactoring parser",
        title="Linear: Refactor parser",
        category=ActionCategory.LINEAR_TICKET,
        details={"title": "Refactor parser", "assignee": "Jake"},
    )
    summary = MeetingActionExecutor.execute_action(act)
    assert act.status == ActionStatus.COMPLETED
    assert "Linear Issue #" in summary
    assert "Assigned to @Jake" in summary


def test_meeting_note_taker_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        taker = MeetingNoteTaker()
        taker._config = VoiceFiConfig()
        taker._config.proactive.meeting_assistant.notes_dir = tmpdir
        taker._config.proactive.meeting_assistant.auto_execute_actions = True

        # Start session
        session = taker.start_session(title="Sprint Demo & Architecture")
        assert session is not None
        assert session.status == "active"
        assert os.path.exists(session.markdown_path)

        # Record turns
        u1 = taker.record_utterance("Welcome everyone to the sprint review.", speaker_name="Jake")
        assert u1.speaker == "Jake"
        assert len(session.utterances) == 1

        u2 = taker.record_utterance("We decided to deploy the new auth service this Friday.")
        assert len(session.decisions) == 1
        assert "Deploy the new auth service" in session.decisions[0].decision

        u3 = taker.record_utterance("Create a linear ticket for updating the API gateway routes")
        assert u3.is_actionable is True
        assert len(session.action_items) == 1
        assert session.action_items[0].status == ActionStatus.COMPLETED

        # Check saved markdown on disk
        with open(session.markdown_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Sprint Demo & Architecture" in content
        assert "Deploy the new auth service" in content
        assert "api gateway routes" in content.lower()

        # Stop session
        final_session = taker.stop_session()
        assert final_session.status == "finalized"
        assert taker.active_session is None

        # List sessions
        saved = taker.list_saved_sessions()
        assert len(saved) == 1
        assert "Sprint Demo & Architecture" in saved[0]["title"]


def test_mcp_server_meeting_tools():
    with tempfile.TemporaryDirectory() as tmpdir:
        server = VoiceFiMCPServer()

        # 1. Start Meeting tool
        resp_start = server.execute_tool(
            "voicefi_meeting_start",
            {"title": "MCP Guided Meeting", "output_path": os.path.join(tmpdir, "mcp_meeting.md")},
        )
        assert resp_start.get("isError") is False
        assert "started successfully" in resp_start["content"][0]["text"]

        # 2. Check Status tool
        resp_status = server.execute_tool("voicefi_meeting_status", {})
        assert resp_status.get("isError") is False
        status_json = json.loads(resp_status["content"][0]["text"])
        assert status_json["status"] == "active"
        assert status_json["title"] == "MCP Guided Meeting"

        # 3. Trigger Action tool (Record decision)
        resp_act1 = server.execute_tool(
            "voicefi_meeting_action",
            {"action_type": "decision", "title": "Adopt MCP architecture across all agent tools"},
        )
        assert resp_act1.get("isError") is False
        assert "Recorded Decision" in resp_act1["content"][0]["text"]

        # 4. Trigger Action tool (Linear issue)
        resp_act2 = server.execute_tool(
            "voicefi_meeting_action",
            {
                "action_type": "linear_ticket",
                "title": "Implement WebRTC streaming endpoint",
                "details": {"assignee": "Jake"},
            },
        )
        assert resp_act2.get("isError") is False
        assert "Executed Meeting Action [LINEAR_TICKET]" in resp_act2["content"][0]["text"]

        # 5. Stop Meeting tool
        resp_stop = server.execute_tool("voicefi_meeting_stop", {})
        assert resp_stop.get("isError") is False
        assert "Meeting Session Finalized!" in resp_stop["content"][0]["text"]
        assert "Adopt MCP architecture across all agent tools" in resp_stop["content"][0]["text"]
