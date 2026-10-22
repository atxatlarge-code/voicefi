"""
Unit and integration tests for `vifi replay` (Zero-Cost Retry & Re-Routing)
and the 10-utterance ring buffer at /tmp/vifi_history.jsonl.
"""

import asyncio
import json
import os
from pathlib import Path
import pytest

from voicefi.cli_parser import build_parser
from voicefi.cli_commands.dispatch import cmd_replay
from voicefi.ipc.history import (
    MAX_HISTORY_ENTRIES,
    dispatch_payload_over_socket,
    get_last_utterance,
    load_utterance_history,
    record_utterance_history,
)
from voicefi.ipc.protocol import METHOD_PROMPT_DISPATCH, parse_jsonrpc_message
from voicefi.ipc.server import VoiceFiIPCServer


def test_ring_buffer_keeps_last_10_utterances(tmp_path):
    history_file = tmp_path / "vifi_history.jsonl"

    for i in range(15):
        record_utterance_history(
            transcript=f"Architectural thought number {i}",
            target_route="antigravity" if i % 2 == 0 else "claude",
            audio_duration=float(i + 1.5),
            timestamp=1700000000.0 + i,
            history_path=history_file,
        )

    lines = history_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == MAX_HISTORY_ENTRIES == 10

    entries = load_utterance_history(history_path=history_file)
    assert len(entries) == 10
    assert entries[0]["transcript"] == "Architectural thought number 5"
    assert entries[-1]["transcript"] == "Architectural thought number 14"
    assert entries[-1]["payload"] == "Architectural thought number 14"
    assert entries[-1]["audio_duration"] == 15.5
    assert entries[-1]["target_route"] == "antigravity"
    assert entries[-1]["timestamp"] == 1700000014.0

    last = get_last_utterance(history_path=history_file)
    assert last is not None
    assert last["transcript"] == "Architectural thought number 14"


def test_daemon_writes_history_before_dispatching_over_socket(tmp_path, monkeypatch):
    async def _run():
        sock_path = f"/tmp/test_vifi_replay_{os.getpid()}.sock"
        history_file = tmp_path / "vifi_history.jsonl"

        server = VoiceFiIPCServer(
            socket_path=sock_path,
            enable_ws=False,
            history_path=str(history_file),
        )
        await server.start()
        try:
            reader, writer = await asyncio.open_unix_connection(sock_path)
            await asyncio.sleep(0.03)

            await server.broadcast_prompt_dispatch(
                transcript="Refactor the event bus to use lock-free ring buffers",
                session_id="conv-42",
                source="whisperkit",
                audio_duration=45.2,
                target_route="antigravity",
            )

            # Verify ring buffer was written right before socket dispatch
            assert history_file.is_file()
            last = get_last_utterance(history_path=history_file)
            assert last is not None
            assert last["transcript"] == "Refactor the event bus to use lock-free ring buffers"
            assert last["audio_duration"] == 45.2
            assert last["target_route"] == "antigravity"
            assert last["session_id"] == "conv-42"

            # Verify socket client received the payload + metadata
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            msg = parse_jsonrpc_message(line)
            assert msg["method"] == METHOD_PROMPT_DISPATCH
            assert (
                msg["params"]["transcript"]
                == "Refactor the event bus to use lock-free ring buffers"
            )
            assert msg["params"]["target_route"] == "antigravity"
            assert msg["params"]["audio_duration"] == 45.2

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

    asyncio.run(_run())


def test_vifi_replay_print_to_stdout(tmp_path, capsys):
    history_file = tmp_path / "vifi_history.jsonl"
    spoken_thought = (
        "Extract the authentication middleware into a zero-dependency Cloudflare Worker"
    )
    record_utterance_history(
        transcript=spoken_thought,
        target_route="antigravity",
        audio_duration=42.8,
        history_path=history_file,
    )

    parser = build_parser(prog="vifi")
    args = parser.parse_args(
        ["replay", "--print", "--history-file", str(history_file)]
    )
    rc = cmd_replay(args)
    assert rc == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == spoken_thought
    assert captured.err == ""


def test_vifi_replay_immediate_redispatch_and_reroute(tmp_path, monkeypatch, capsys):
    history_file = tmp_path / "vifi_history.jsonl"
    spoken_thought = "Migrate the WebSocket state machine to durable objects with hibernatable connections"
    record_utterance_history(
        transcript=spoken_thought,
        target_route="antigravity",
        audio_duration=44.5,
        session_id="conv-orig",
        history_path=history_file,
    )

    dispatched_calls = []

    class DummyResult:
        success = True
        delivery_type = "ipc"
        error = None

    def _mock_send_message_to_agent(**kwargs):
        dispatched_calls.append(kwargs)
        return DummyResult()

    monkeypatch.setattr(
        "voicefi.integrations.injector.send_message_to_agent",
        _mock_send_message_to_agent,
    )

    parser = build_parser(prog="vifi")

    # 1. `vifi replay` — immediate retry to original route (antigravity)
    args1 = parser.parse_args(["replay", "--history-file", str(history_file)])
    rc1 = cmd_replay(args1)
    assert rc1 == 0
    assert len(dispatched_calls) == 1
    assert dispatched_calls[0]["text"] == spoken_thought
    assert dispatched_calls[0]["target_engine"] == "antigravity"
    assert dispatched_calls[0]["conv_id"] == "conv-orig"

    # 2. `vifi replay --to claude` — re-route exact spoken thought to a different handler
    args2 = parser.parse_args(
        ["replay", "--to", "claude", "--history-file", str(history_file)]
    )
    rc2 = cmd_replay(args2)
    assert rc2 == 0
    assert len(dispatched_calls) == 2
    assert dispatched_calls[1]["text"] == spoken_thought
    assert dispatched_calls[1]["target_engine"] == "claude"
    out = capsys.readouterr().out
    assert "re-routed from antigravity ➔ claude" in out


def test_vifi_replay_over_unix_socket(tmp_path, monkeypatch):
    async def _run():
        sock_path = f"/tmp/test_vifi_sock_{os.getpid()}.sock"
        history_file = tmp_path / "vifi_history.jsonl"
        spoken_thought = "Add backpressure control to the Metal GPU inference queue"

        record_utterance_history(
            transcript=spoken_thought,
            target_route="spark",
            audio_duration=19.4,
            history_path=history_file,
        )

        received_events = []
        server = VoiceFiIPCServer(
            socket_path=sock_path,
            enable_ws=False,
            history_path=str(history_file),
            on_prompt_dispatch=lambda params: received_events.append(params),
        )
        await server.start()
        try:
            # Dispatch replay to the socket on a background thread so the event loop can accept it
            parser = build_parser(prog="vifi")
            args = parser.parse_args(
                [
                    "replay",
                    "--to",
                    "ipc",
                    "--socket",
                    sock_path,
                    "--history-file",
                    str(history_file),
                ]
            )
            loop = asyncio.get_running_loop()
            rc = await loop.run_in_executor(None, cmd_replay, args)
            assert rc == 0

            await asyncio.sleep(0.05)
            assert len(received_events) == 1
            assert received_events[0]["transcript"] == spoken_thought
            assert received_events[0]["target_route"] == "ipc"
            assert received_events[0]["audio_duration"] == 19.4
        finally:
            await server.stop()

    asyncio.run(_run())
