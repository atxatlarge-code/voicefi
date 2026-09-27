"""
Unit tests for traceback and error anomaly parser.
"""

import pytest
from voicefi.local.trace_parser import (
    parse_traceback,
    extract_python_frames,
    extract_js_frames,
    extract_pytest_failure,
    extract_error_line,
)


def test_extract_python_traceback(tmp_path):
    f = tmp_path / "engine.py"
    f.write_text("def run(): pass")

    sample_trace = f"""
Traceback (most recent call last):
  File "/Users/test/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 467, in urlopen
    self._make_request(conn, method, url, timeout=timeout_obj, body=body, headers=headers)
  File "{f}", line 42, in start_engine
    sock.connect(addr)
ConnectionRefusedError: [Errno 61] Connection refused
"""
    parsed = parse_traceback(sample_trace)
    assert parsed.target_file == str(f.resolve())
    assert parsed.line_number == 42
    assert parsed.error_type == "ConnectionRefusedError"
    assert "Connection refused" in parsed.error_message
    assert "around line 42" in parsed.instruction


def test_extract_pytest_failure():
    sample_pytest = """
=================================== FAILURES ===================================
_________________________________ test_battery _________________________________

    def test_battery():
>       assert get_level() == 100
E       AssertionError: assert 85 == 100

FAILED tests/test_battery.py::test_battery - AssertionError: assert 85 == 100
"""
    parsed = parse_traceback(sample_pytest)
    assert parsed.error_type == "AssertionError"
    assert "assert 85 == 100" in parsed.error_message


def test_extract_js_traceback(tmp_path):
    f = tmp_path / "client.ts"
    f.write_text("export function connect() {}")

    sample_js = f"""
TypeError: Cannot read properties of undefined (reading 'token')
    at Object.authenticate (/Users/test/node_modules/auth/index.js:55:12)
    at handleLogin ({f}:88:15)
    at process.processTicksAndRejections (node:internal/process/task_queues:95:5)
"""
    parsed = parse_traceback(sample_js)
    assert parsed.target_file == str(f.resolve())
    assert parsed.line_number == 88
    assert parsed.error_type == "TypeError"
    assert "Cannot read properties" in parsed.error_message


def test_fallback_instruction():
    raw = "Fix timeout issue with websocket reconnect"
    parsed = parse_traceback(raw)
    assert parsed.target_file is None
    assert "Fix" in parsed.instruction
