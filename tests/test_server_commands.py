"""
Unit tests for VoiceFi Server commands, flat action shortcuts (status, stop, start, restart),
and backward-compatible daemon/service aliases.
"""

import argparse
import pytest
from unittest.mock import patch, MagicMock

import voicefi.server as v_server
import voicefi.daemon as v_daemon
import voicefi.integrations.server_client as sc_client
import voicefi.integrations.daemon_client as dc_client
from voicefi.cli import cmd_server, cmd_clean, cmd_dev, VoiceFiArgumentParser


def test_server_and_daemon_export_parity():
    """Ensure voicefi.daemon exports all functions and aliases from voicefi.server."""
    assert v_server.get_full_server_status == v_daemon.get_full_daemon_status
    assert v_server.stop_all_voicefi_servers == v_daemon.stop_all_voicefi_daemons
    assert v_server.clean_caches == v_daemon.clean_caches
    assert v_server.clean_lock_files == v_daemon.clean_lock_files
    assert v_server.link_dev_environment == v_daemon.link_dev_environment


def test_server_client_and_daemon_client_parity():
    """Ensure daemon_client compatibility shim re-exports server_client correctly."""
    assert sc_client.is_server_running == dc_client.is_daemon_running
    assert sc_client.ensure_server_running == dc_client.ensure_daemon_running
    assert sc_client.forward_hook_to_server == dc_client.forward_hook_to_daemon


def test_cmd_server_status(capsys):
    """Test cmd_server status action outputs modern server status banner."""
    mock_status = {
        "launchagent": {"is_loaded": True, "pid": 12345, "plist_exists": True, "plist_path": "/path/plist"},
        "port_5141": {"pid": 12345, "command_name": "voicefi"},
        "port_8765": None,
        "port_listener": None,
        "running_processes": [{"pid": 12345, "ppid": 1, "command": "voicefi tray"}],
        "lock_active": False,
        "pid_file": {"pid": 12345},
        "hooks": {"antigravity": "voicefi hook", "claude": "voicefi hook --agent claude"},
        "python_executable": "/usr/bin/python3",
    }
    with patch("voicefi.server.get_full_server_status", return_value=mock_status):
        cmd_server(argparse.Namespace(server_action="status"))

    out = capsys.readouterr().out
    assert "VoiceFi Server & Runtime Status" in out
    assert "LaunchAgent (launchd):  🟢 Loaded (PID 12345)" in out
    assert "Port 5141 Owner:        🟢 PID 12345 (voicefi)" in out
    assert "vifi status" in out


def test_cmd_server_stop(capsys):
    """Test cmd_server stop terminates servers and reports status."""
    with patch("voicefi.server.stop_all_voicefi_servers", return_value={"stopped_pids": [12345], "port_freed": True}):
        cmd_server(argparse.Namespace(server_action="stop"))

    out = capsys.readouterr().out
    assert "Stopping all VoiceFi background servers" in out
    assert "Terminated processes: [12345]" in out
    assert "Port 5141 freed" in out


def test_cmd_server_restart(capsys):
    """Test cmd_server restart stops servers, cleans cache, and triggers autostart."""
    with patch("voicefi.server.stop_all_voicefi_servers") as mock_stop, \
         patch("voicefi.server.clean_caches") as mock_clean, \
         patch("voicefi.cli.cmd_autostart") as mock_autostart:
        cmd_server(argparse.Namespace(server_action="restart"))
        assert mock_stop.called
        assert mock_clean.called
        assert mock_autostart.called


def test_cli_parser_server_and_flat_shortcuts():
    """Test CLI argument parsing for status, stop, start, restart, server, and daemon aliases."""
    import sys
    from voicefi.cli import main

    # 1. Test 'status' shortcut
    parser = VoiceFiArgumentParser(prog="vifi")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status")
    subparsers.add_parser("stop")
    subparsers.add_parser("start")
    subparsers.add_parser("restart")
    server_p = subparsers.add_parser("server", aliases=["daemon", "service"])
    server_p.add_argument("server_action", nargs="?", default="status")

    args = parser.parse_args(["status"])
    assert args.command == "status"

    args = parser.parse_args(["stop"])
    assert args.command == "stop"

    args = parser.parse_args(["start"])
    assert args.command == "start"

    args = parser.parse_args(["restart"])
    assert args.command == "restart"

    args = parser.parse_args(["server", "stop"])
    assert args.command == "server"
    assert args.server_action == "stop"

    args = parser.parse_args(["daemon", "status"])
    assert args.command in ("daemon", "server")
    assert args.server_action == "status"

    args = parser.parse_args(["service", "restart"])
    assert args.command in ("service", "server")
    assert args.server_action == "restart"
