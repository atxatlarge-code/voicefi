#!/usr/bin/env python3
"""
scripts/local_qa.py
VoiceFi Local QA Diff Auditor & Test Synthesizer.

Runs on-device verification without cloud token burn:
1. Audits current git diff using local Qwen2.5-Coder / Gemma 2 via Ollama.
2. Checks for syntax regressions, unhandled edge cases, and missing imports.
3. Synthesizes proposed missing unit test cases.
4. Runs local linter (ruff) and pytest suites.
5. Emits a clean, actionable markdown scorecard to .agents/QA_AUDIT.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voicefi.local.supervisor import default_supervisor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voicefi.qa")


def get_git_diff(
    staged_only: bool = False,
    revision: Optional[str] = None,
    max_chars: int = 40_000,
) -> tuple[str, list[str]]:
    """Capture current git diff and list of changed files."""
    if revision:
        cmd = ["git", "diff", revision]
        name_cmd = ["git", "diff", "--name-only", revision]
    elif staged_only:
        cmd = ["git", "diff", "--cached"]
        name_cmd = ["git", "diff", "--name-only", "--cached"]
    else:
        cmd = ["git", "diff", "HEAD"]
        name_cmd = ["git", "diff", "--name-only", "HEAD"]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        diff_text = res.stdout
    except Exception as e:
        logger.error(f"Failed to get git diff: {e}")
        return "", []

    try:
        name_res = subprocess.run(name_cmd, capture_output=True, text=True, check=True)
        files = [f.strip() for f in name_res.stdout.splitlines() if f.strip()]
    except Exception:
        files = []

    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars] + f"\n\n... [Diff truncated to {max_chars} chars] ..."

    return diff_text, files


def run_ruff_lint(files: list[str]) -> tuple[bool, str]:
    """Run ruff check on changed Python files."""
    py_files = [f for f in files if f.endswith(".py") and os.path.exists(f)]
    if not py_files:
        return True, "No modified Python files to lint."

    try:
        res = subprocess.run(
            ["uv", "run", "ruff", "check"] + py_files[:20],
            capture_output=True,
            text=True,
            timeout=20.0,
        )
        passed = (res.returncode == 0)
        output = res.stdout.strip() or res.stderr.strip()
        return passed, output or "All lint checks passed cleanly."
    except Exception as e:
        return False, f"Ruff execution error: {e}"


def run_targeted_tests(test_target: str = "tests/") -> tuple[bool, str]:
    """Run pytest on targeted tests."""
    try:
        res = subprocess.run(
            ["uv", "run", "pytest", test_target, "-q", "--maxfail=3"],
            capture_output=True,
            text=True,
            timeout=45.0,
        )
        passed = (res.returncode == 0)
        output = res.stdout.strip()
        return passed, output
    except Exception as e:
        return False, f"Pytest execution error: {e}"


def query_local_model_audit(diff_text: str, changed_files: list[str]) -> tuple[str, str, int]:
    """Audit diff using local Ollama model."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    preferred_models = ["qwen2.5-coder:1.5b", "gemma2:2b", "llama3.2:1b", "tev1:latest"]
    selected_model = None

    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
            installed = [m.get("name", "") for m in data.get("models", [])]
            for p in preferred_models:
                if p in installed:
                    selected_model = p
                    break
            if not selected_model and installed:
                selected_model = installed[0]
    except Exception as e:
        logger.warning(f"Could not connect to Ollama: {e}")
        return "Heuristic fallback (Ollama unavailable)", "N/A", 0

    system_prompt = (
        "You are the VoiceFi Local QA Engineer. You analyze git diffs to detect regressions, "
        "type errors, concurrency deadlocks, and unhandled edge cases. "
        "Format your answer as: \n"
        "1. Risk Assessment (Low/Medium/High)\n"
        "2. Potential Edge Cases & Vulnerabilities\n"
        "3. Proposed Missing Unit Test Cases (provide exact def test_* functions)"
    )

    prompt = (
        f"Modified Files ({len(changed_files)}):\n"
        + "\n".join(f"- {f}" for f in changed_files[:15])
        + f"\n\nGit Diff:\n```diff\n{diff_text}\n```\n\n"
        "Perform a thorough technical code review and synthesize missing unit test signatures."
    )

    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 700,
        },
    }

    try:
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=35.0) as resp:
            if resp.status == 200:
                res = json.loads(resp.read().decode())
                content = res.get("message", {}).get("content", "").strip()
                tokens = res.get("eval_count", 0) + res.get("prompt_eval_count", 0)
                return content, selected_model, tokens
    except Exception as e:
        logger.error(f"Local QA model inference failed: {e}")

    return "Failed to complete model audit.", "error", 0


def main():
    parser = argparse.ArgumentParser(description="VoiceFi On-Device QA Diff Auditor")
    parser.add_argument("--staged", action="store_true", help="Audit only staged changes")
    parser.add_argument("--rev", "--revision", dest="revision", type=str, default=None, help="Git revision or commit range (e.g. HEAD~1 or main..HEAD)")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running pytest")
    parser.add_argument("--test-target", type=str, default="tests/test_content_factory.py", help="Pytest target")
    parser.add_argument("--output-file", type=str, default=".agents/QA_AUDIT.md", help="Output report file")
    args = parser.parse_args()

    # Hardware check
    default_supervisor.wait_if_throttled(poll_interval=2.0, max_wait=10.0)

    logger.info("Inspecting git diff...")
    diff_text, changed_files = get_git_diff(staged_only=args.staged, revision=args.revision)

    if not diff_text.strip() and not args.revision and not args.staged:
        logger.info("Working tree clean. Falling back to latest commit (HEAD~1)...")
        diff_text, changed_files = get_git_diff(revision="HEAD~1")

    if not diff_text.strip():
        logger.info("No git changes detected.")
        print("✅ No git changes to audit.")
        return

    logger.info(f"Auditing diff across {len(changed_files)} files ({len(diff_text)} chars)...")

    # 1. Run Ruff Linter
    logger.info("Running local linter (ruff)...")
    lint_passed, lint_output = run_ruff_lint(changed_files)

    # 2. Run Pytest if requested
    test_passed = True
    test_output = "Skipped"
    if not args.skip_tests:
        logger.info(f"Running targeted unit tests ({args.test_target})...")
        test_passed, test_output = run_targeted_tests(args.test_target)

    # 3. Model Review & Test Synthesis
    logger.info("Querying local model for architectural review & test synthesis...")
    t0 = time.time()
    review_content, model_used, tokens_used = query_local_model_audit(diff_text, changed_files)
    elapsed = round(time.time() - t0, 2)

    # 4. Generate Report
    report = [
        "# 🛡️ VoiceFi Local QA Audit & Verification Scorecard",
        f"- **Model**: `{model_used}` (On-Device via Ollama, $0 Cloud Cost)",
        f"- **Inference Duration**: {elapsed}s (~{tokens_used} local tokens processed)",
        f"- **Scope**: {len(changed_files)} modified files",
        "",
        "## 🚦 Automated Test & Lint Gates",
        f"- **Linter (`ruff`)**: {'✅ PASS' if lint_passed else '❌ FAIL'}",
        f"```text\n{lint_output[:400]}\n```" if lint_output else "",
        f"- **Targeted Tests (`pytest`)**: {'✅ PASS' if test_passed else '❌ FAIL'}",
        f"```text\n{test_output[:400]}\n```" if test_output else "",
        "",
        "## 🔬 Local Model Architectural Review & Edge-Case Synthesis",
        review_content,
        "",
        "---",
        f"*Generated automatically on Apple Silicon at {time.strftime('%Y-%m-%d %H:%M:%S')}*",
    ]

    report_str = "\n".join(report)

    # Write output
    out_path = Path(args.output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_str, encoding="utf-8")

    logger.info(f"QA audit scorecard written to {out_path}")
    print("\n" + report_str)


if __name__ == "__main__":
    main()
