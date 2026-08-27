"""
Tests for Tool Call and Log Output Formatter.
"""

from voicefi.integrations.tool_formatter import format_tool_details, extract_log_summary


def test_format_tool_details_run_command():
    # 1. Standard run_command with CommandLine
    tc = {
        "name": "run_command",
        "args": {
            "CommandLine": "pytest tests/test_hud.py -v",
            "Cwd": "/Users/jaketrigg/Projects/VoiceFi",
            "toolAction": "Running test suite",
            "toolSummary": "Run pytest",
        },
    }
    desc, tag = format_tool_details(tc)
    assert tag == "Running Command"
    assert "pytest tests/test_hud.py -v" in desc

    # 2. Generic action fallback
    tc_generic = {
        "name": "run_command",
        "args": {
            "CommandLine": "git status --short",
            "toolAction": "Running command",
            "toolSummary": "Command execution",
        },
    }
    desc, tag = format_tool_details(tc_generic)
    assert tag == "Running Command"
    assert desc == "git status --short"

    # 3. Claude Bash format
    tc_claude = {
        "type": "tool_use",
        "name": "Bash",
        "input": {
            "command": "cargo check --all-targets",
        },
    }
    desc, tag = format_tool_details(tc_claude)
    assert tag == "Running Command"
    assert desc == "cargo check --all-targets"


def test_format_tool_details_file_operations():
    # 1. view_file
    tc_view = {
        "name": "view_file",
        "args": {
            "AbsolutePath": "/Users/jaketrigg/Projects/VoiceFi/src/voicefi/ui/unified_hud.py",
            "StartLine": 1100,
            "EndLine": 1160,
        },
    }
    desc, tag = format_tool_details(tc_view)
    assert tag == "Reading File"
    assert desc == "Viewing unified_hud.py (L1100-1160)"

    # 2. replace_file_content
    tc_edit = {
        "name": "replace_file_content",
        "args": {
            "TargetFile": "/Users/jaketrigg/Projects/VoiceFi/src/voicefi/ui/unified_hud.py",
            "Description": "Update HUD dynamic tool badge and subtitles",
        },
    }
    desc, tag = format_tool_details(tc_edit)
    assert tag == "Editing File"
    assert "unified_hud.py" in desc
    assert "Update HUD dynamic" in desc

    # 3. write_to_file
    tc_write = {
        "name": "write_to_file",
        "args": {
            "TargetFile": "/Users/jaketrigg/Projects/VoiceFi/src/voicefi/integrations/tool_formatter.py",
            "Description": "Create tool formatter",
        },
    }
    desc, tag = format_tool_details(tc_write)
    assert tag == "Writing File"
    assert "tool_formatter.py" in desc


def test_format_tool_details_search_and_subagents():
    # 1. grep_search
    tc_grep = {
        "name": "grep_search",
        "args": {
            "Query": "Running Tool",
            "SearchPath": "/Users/jaketrigg/Projects/VoiceFi",
        },
    }
    desc, tag = format_tool_details(tc_grep)
    assert tag == "Searching Code"
    assert desc == 'Grep: "Running Tool"'

    # 2. find_by_name
    tc_find = {
        "name": "find_by_name",
        "args": {
            "Pattern": "*.jsonl",
            "SearchDirectory": "/Users/jaketrigg/.gemini/antigravity",
        },
    }
    desc, tag = format_tool_details(tc_find)
    assert tag == "Finding Files"
    assert desc == "Finding: *.jsonl"

    # 3. invoke_subagent
    tc_subagent = {
        "name": "invoke_subagent",
        "args": {
            "Subagents": [
                {
                    "Role": "Codebase Researcher",
                    "TypeName": "research",
                }
            ]
        },
    }
    desc, tag = format_tool_details(tc_subagent)
    assert tag == "Subagent"
    assert desc == "Subagent: Codebase Researcher"

    # 4. MCP tool
    tc_mcp = {
        "name": "call_mcp_tool",
        "args": {
            "ServerName": "chrome-devtools",
            "ToolName": "navigate_page",
        },
    }
    desc, tag = format_tool_details(tc_mcp)
    assert tag == "MCP Tool"
    assert desc == "MCP: chrome-devtools -> navigate_page"


def test_extract_log_summary():
    # 1. Pytest test results output
    pytest_out = """
============================= test session starts ==============================
rootdir: /Users/jaketrigg/Projects/VoiceFi
collected 318 items

tests/test_hud.py .................................. [ 100%]
============================== 318 passed in 3.42s ===============================
"""
    summary = extract_log_summary(pytest_out)
    assert summary is not None
    assert "318 passed" in summary

    # 2. Compiler / Build Complete output
    build_out = """
[1/5] Compiling VoiceFi.swift
[2/5] Linking libVoiceFi.dylib
Build complete! (0.84s)
"""
    summary = extract_log_summary(build_out)
    assert summary is not None
    assert "Build complete" in summary

    # 3. Search results
    search_out = """
Found 25 results
__init__.py
tool_formatter.py
"""
    summary = extract_log_summary(search_out)
    assert summary is not None
    assert "Found 25 results" in summary

    # 4. Error output
    error_out = """
Traceback (most recent call last):
  File "main.py", line 42, in <module>
ZeroDivisionError: division by zero
"""
    summary = extract_log_summary(error_out)
    assert summary is not None
    assert "ZeroDivisionError: division by zero" in summary

    # 5. Empty or whitespace
    assert extract_log_summary("") is None
    assert extract_log_summary("   \n\n  ") is None

    # 6. Runner metadata filtering (e.g. Created At: 2026)
    timestamp_only = """
Created At: 2026-08-27T06:08:45-05:00
Completed At: 2026-08-27T06:08:45-05:00
"""
    assert extract_log_summary(timestamp_only) is None

    timestamp_with_results = """
Created At: 2026-08-27T06:08:45-05:00
Completed At: 2026-08-27T06:08:45-05:00
{"File":"/Users/jaketrigg/Projects/VoiceFi/src/voicefi/ui/unified_hud.py"}
"""
    summary = extract_log_summary(timestamp_with_results)
    assert summary == "Match in unified_hud.py"

    task_envelope = """
Created At: 2026-08-27T06:08:45-05:00
Tool is running as a background task with task id: 43fd6258-16d1-4ba0-9cd7-e5a690ca19d6/task-67
Task logs are available at: file:///Users/jaketrigg/...
YOU MUST TAKE ONE OF THE FOLLOWING TWO ACTIONS: A) either proceed to other relevant work
DO NOTHING ELSE.
"""
    assert extract_log_summary(task_envelope) is None

