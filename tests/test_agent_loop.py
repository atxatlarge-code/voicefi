"""
Unit tests for VoiceFi LocalAutonomousLoop.
Verifies multi-turn tool calling, surgical diff application, command execution, and finish handling.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch
import pytest

from voicefi.local.agent_loop import LocalAutonomousLoop, AutonomousLoopResult


@pytest.fixture
def temp_project(tmp_path):
    src_file = tmp_path / "app.py"
    src_file.write_text(
        '''
def greet():
    print("hello world")

def calculate(a, b):
    return a + b
'''
    )
    return tmp_path


def test_agent_loop_tool_execution(temp_project):
    loop = LocalAutonomousLoop(repo_root=temp_project)

    # 1. read_slice
    res_slice = loop._execute_tool("read_slice", {"path": "app.py", "start_line": 2, "end_line": 3})
    assert "def greet():" in res_slice
    assert 'print("hello world")' in res_slice

    # 2. apply_diff
    search = '    print("hello world")'
    replace = '    print("hello from autonomous local loop")'
    res_diff = loop._execute_tool("apply_diff", {"path": "app.py", "search": search, "replace": replace})
    assert "Successfully applied" in res_diff

    # Verify file content updated
    updated_text = (temp_project / "app.py").read_text()
    assert "hello from autonomous local loop" in updated_text

    # 3. run_command
    res_cmd = loop._execute_tool("run_command", {"command": "echo 'LOCAL_TEST_OK'"})
    assert "[SUCCESS]" in res_cmd
    assert "LOCAL_TEST_OK" in res_cmd

    # 4. Security check on dangerous commands
    res_sec = loop._execute_tool("run_command", {"command": "sudo rm -rf /"})
    assert "Disallowed destructive command" in res_sec


@pytest.mark.asyncio
async def test_agent_loop_multiturn_flow(temp_project):
    loop = LocalAutonomousLoop(repo_root=temp_project, max_turns=3)

    # Mock the model responses for a 2-turn execution:
    # Turn 1: Model reads slice
    # Turn 2: Model finishes task
    mock_responses = [
        'THOUGHT: Let me view the greet function.\n```json\n{"tool": "read_slice", "arguments": {"path": "app.py", "start_line": 2, "end_line": 4}}\n```',
        'THOUGHT: Everything is verified.\n```json\n{"tool": "finish", "arguments": {"summary": "Reviewed greet function successfully."}}\n```',
    ]

    with patch.object(loop, "_query_model", side_effect=mock_responses):
        res = await loop.execute(goal="Check greeting in app.py")

        assert res.completed is True
        assert res.summary == "Reviewed greet function successfully."
        assert len(res.steps) == 2
        assert res.steps[0].tool == "read_slice"
        assert res.steps[1].tool == "finish"
