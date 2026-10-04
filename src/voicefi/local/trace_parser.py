"""
Traceback and error anomaly parser for VoiceFi bug resolution.
Extracts target files, line numbers, and error summaries from stack traces,
compiler errors, and test outputs across Python, TypeScript/JavaScript, and Rust.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


IGNORE_PATH_PATTERNS = [
    r"[\\/]\.venv[\\/]",
    r"[\\/]site-packages[\\/]",
    r"[\\/]node_modules[\\/]",
    r"[\\/]usr[\\/]",
    r"[\\/]System[\\/]Library[\\/]",
    r"^node:",
    r"node:internal",
    r"<string>",
    r"<stdin>",
    r"<frozen\s+",
    r"<anonymous>",
]


@dataclass
class ParsedTrace:
    target_file: Optional[str]
    line_number: Optional[int]
    error_type: Optional[str]
    error_message: Optional[str]
    instruction: str
    raw_trace: str

    @property
    def has_target(self) -> bool:
        return bool(self.target_file and os.path.exists(self.target_file))


def is_user_project_path(path_str: str) -> bool:
    """Check if a file path belongs to user project code rather than libraries or virtualenvs."""
    for pattern in IGNORE_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return False
    return True


def extract_python_frames(text: str) -> List[Tuple[str, int]]:
    """Extract (file_path, line_number) from Python tracebacks."""
    pattern = re.compile(r'File\s+["\']([^"\']+)["\'],\s+line\s+(\d+)', re.IGNORECASE)
    frames = []
    for match in pattern.finditer(text):
        file_path = match.group(1).strip()
        line_num = int(match.group(2))
        if is_user_project_path(file_path):
            frames.append((file_path, line_num))
    return frames


def extract_js_frames(text: str) -> List[Tuple[str, int]]:
    """Extract (file_path, line_number) from JS/TS tracebacks."""
    # Matches: at func (/path/file.ts:12:3) OR at /path/file.ts:12:3
    pattern = re.compile(
        r"at\s+(?:[^\(\n\r]+\((.+?):(\d+):\d+\)|(.+?):(\d+):\d+)",
        re.IGNORECASE,
    )
    frames = []
    for match in pattern.finditer(text):
        file_path = (match.group(1) or match.group(3) or "").strip()
        line_str = match.group(2) or match.group(4)
        if file_path and line_str and is_user_project_path(file_path):
            frames.append((file_path, int(line_str)))
    return frames


def extract_pytest_failure(text: str) -> Optional[Tuple[str, Optional[int]]]:
    """Extract failing test or source file from pytest output."""
    # Matches: FAILED tests/test_foo.py::test_bar
    fail_pattern = re.compile(r"FAILED\s+([^\s:]+\.(?:py|ts|js))(?:::([^\s]+))?", re.IGNORECASE)
    match = fail_pattern.search(text)
    if match:
        file_path = match.group(1).strip()
        return (file_path, None)

    # Matches: >   line of failing code with ___ in file.py:123 ___
    header_pattern = re.compile(r"_{3,}\s+([^\s]+\.(?:py|ts|js)):(\d+)\s+_{3,}")
    match = header_pattern.search(text)
    if match:
        return (match.group(1).strip(), int(match.group(2)))

    return None


def extract_error_line(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract exception type and message from the end of a traceback."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None, None

    # Search backwards for Exception: message
    for line in reversed(lines):
        # Python exception format: ValueError: invalid literal ...
        py_match = re.match(
            r"^([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning|Fault))(?::\s*(.*))?$", line
        )
        if py_match:
            return py_match.group(1), py_match.group(2) or ""

        # Pytest assertion failure: E   AssertionError: ...
        pytest_match = re.match(
            r"^E\s+([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))(?::\s*(.*))?$", line
        )
        if pytest_match:
            return pytest_match.group(1), pytest_match.group(2) or ""

        # JS error: Error: something went wrong
        js_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*Error):\s*(.*)$", line)
        if js_match:
            return js_match.group(1), js_match.group(2) or ""

    # Fallback to the last non-empty line as general error description
    return "Error", lines[-1]


def parse_traceback(raw_text: str, fallback_target: Optional[str] = None) -> ParsedTrace:
    """
    Parse a raw error log, traceback, or test output and resolve the target file,
    line number, error type, and constructed instruction for code generation.
    """
    cleaned = raw_text.strip()
    target_file: Optional[str] = None
    line_number: Optional[int] = None

    # 1. Try Python tracebacks (deepest user frame)
    py_frames = extract_python_frames(cleaned)
    if py_frames:
        target_file, line_number = py_frames[-1]

    # 2. Try JS/TS tracebacks
    if not target_file:
        js_frames = extract_js_frames(cleaned)
        if js_frames:
            target_file, line_number = js_frames[-1]

    # 3. Try pytest failure lines
    if not target_file:
        pytest_info = extract_pytest_failure(cleaned)
        if pytest_info:
            target_file, line_number = pytest_info

    # 4. Fallback: check if fallback_target or any file exists in text
    if not target_file and fallback_target:
        target_file = fallback_target

    if not target_file:
        # Search for any referenced source files existing in current directory
        file_candidates = re.findall(
            r"([a-zA-Z0-9_\-\./\\]+\.(?:py|ts|tsx|js|jsx|rs|go|swift))", cleaned
        )
        for cand in file_candidates:
            if is_user_project_path(cand) and os.path.isfile(cand):
                target_file = cand
                break

    # Resolve target file to canonical path if existing
    if target_file and os.path.exists(target_file):
        target_file = str(Path(target_file).resolve())

    error_type, error_msg = extract_error_line(cleaned)

    # Build actionable instruction
    parts = []
    if error_type and error_msg:
        parts.append(f"Fix {error_type}: {error_msg}")
    elif error_msg:
        parts.append(f"Fix error: {error_msg}")
    else:
        parts.append("Fix the error reported in the traceback")

    if line_number:
        parts.append(f"around line {line_number}")

    instruction = " ".join(parts).strip()

    return ParsedTrace(
        target_file=target_file,
        line_number=line_number,
        error_type=error_type,
        error_message=error_msg,
        instruction=instruction,
        raw_trace=cleaned,
    )
