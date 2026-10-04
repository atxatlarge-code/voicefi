"""
CLI command: vifi fix
Zero-friction bug resolution via local models (Gemma 4 2B/26B on Metal or Qwen Coder).
Accepts tracebacks from stdin (piped from pytest/npm), macOS clipboard (--clip), or CLI args.
Includes a 2-attempt self-healing verification budget.
"""

import asyncio
import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Any, Optional, Tuple

from voicefi.local.trace_parser import parse_traceback
from voicefi.local.implementer import ReconImplementer, ImplementResult


def read_clipboard() -> str:
    """Read contents of macOS system clipboard via pbpaste."""
    try:
        res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
        return res.stdout.strip()
    except Exception as e:
        print(f"⚠️ Could not read clipboard: {e}", file=sys.stderr)
        return ""


def run_test_command(command: str) -> Tuple[bool, str]:
    """Execute a verification command and return (passed, output)."""
    try:
        sub_env = os.environ.copy()
        py_bin = os.path.dirname(sys.executable)
        sub_env["PATH"] = f"{py_bin}:{sub_env.get('PATH', '')}"

        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            env=sub_env,
        )
        combined = (res.stdout + "\n" + res.stderr).strip()
        return (res.returncode == 0, combined)
    except Exception as e:
        return (False, f"Test execution failed with exception: {e}")


def cmd_fix(args: Any) -> int:
    """
    Execute on-device bug resolution.
    Returns 0 on success, non-zero on failure.
    """
    raw_input_text = ""
    fallback_target = getattr(args, "target", None)

    # 1. Read from stdin if piped (e.g. pytest | vifi fix)
    if not sys.stdin.isatty():
        try:
            raw_input_text = sys.stdin.read().strip()
        except Exception:
            raw_input_text = ""

    # 2. Or read from clipboard if --clip flag is specified
    if not raw_input_text and getattr(args, "clip", False):
        print("📋 Reading bug/traceback from macOS clipboard...")
        raw_input_text = read_clipboard()

    # 3. Or read from explicit error argument
    explicit_error = getattr(args, "error", None)
    if explicit_error:
        raw_input_text = (raw_input_text + "\n" + explicit_error).strip()

    # 4. If target is provided but no error text, treat target as instruction or file
    if not raw_input_text and fallback_target:
        if os.path.exists(fallback_target):
            # Target is a file, ask for instruction or read stdin
            raw_input_text = getattr(args, "instruction", "") or f"Fix bug in {fallback_target}"
        else:
            # Target is the error description itself
            raw_input_text = fallback_target
            fallback_target = None

    if not raw_input_text and not fallback_target:
        print("❌ Error: No bug, stack trace, or file provided.")
        print("Usage:")
        print("  vifi fix <file> -e 'error message'")
        print("  vifi fix --clip")
        print("  pytest | vifi fix")
        return 1

    # Parse traceback
    parsed = parse_traceback(raw_input_text, fallback_target=fallback_target)

    target_file = parsed.target_file
    if not target_file:
        print("❌ Could not determine target source file from the provided error/traceback.")
        print("   Please specify the target file explicitly:")
        print(f"   vifi fix <path/to/file> -e '{parsed.instruction}'")
        return 1

    target_path = Path(target_file).resolve()
    if not target_path.exists():
        print(f"❌ Target file does not exist: {target_path}")
        return 1

    instruction = parsed.instruction
    if getattr(args, "instruction", None):
        instruction = f"{instruction}. {args.instruction}"

    apply = getattr(args, "apply", True)
    test_cmd = getattr(args, "test", None)
    model_scout = getattr(args, "model_scout", "gemma4-2b") or "gemma4-2b"
    model_coder = getattr(args, "model_coder", "gemma4-26b") or "gemma4-26b"

    print(f"\n🎯 Target File : {target_path}")
    if parsed.line_number:
        print(f"📍 Line Number : {parsed.line_number}")
    if parsed.error_type:
        print(f"💥 Error Type  : {parsed.error_type}")
    print(f"🛠️  Task        : {instruction}")
    print(f"⚡ Local Models: {model_scout} (Scout) ➔ {model_coder} (Coder)")
    print("-" * 60)

    implementer = ReconImplementer(model_scout=model_scout, model_coder=model_coder)

    # -----------------------------------------------------------------
    # Attempt 1
    # -----------------------------------------------------------------
    print("🚀 [Attempt 1/2] Generating local patch...")
    res: ImplementResult = asyncio.run(
        implementer.implement(target_path=target_path, instruction=instruction, apply=apply)
    )

    if res.error and not res.diff:
        print(f"❌ Attempt 1 failed to generate patch: {res.error}")
        return 1

    if not res.diff.strip():
        print("⚠️ No changes were made by the local model.")
        return 1

    print(f"\n📄 Unified Diff (Attempt 1):\n{res.diff}\n")
    print(f"💰 Token Savings: {res.tokens_saved} tokens ({res.savings_pct}% context preserved)")

    # If no test command specified, we are done with Attempt 1!
    if not test_cmd or not apply:
        if not apply:
            print("🔍 Dry Run completed. Changes not written to disk.")
        else:
            print(f"✅ Patch applied to `{target_path.name}`.")
        return 0

    # Run verification test
    print(f"🧪 Running verification command: `{test_cmd}`...")
    passed, test_output = run_test_command(test_cmd)

    if passed:
        print(f"✅ Verification PASSED! `{target_path.name}` fixed on Attempt 1.")
        return 0

    # -----------------------------------------------------------------
    # Attempt 2 (Self-Healing Feedback Loop)
    # -----------------------------------------------------------------
    print(f"⚠️ Verification FAILED on Attempt 1:\n{test_output[-500:]}\n")
    print("🔄 [Attempt 2/2] Feeding test failure back to local model for self-healing turn...")

    retry_instruction = (
        f"{instruction}\n\n"
        f"IMPORTANT: The previous patch failed the verification command `{test_cmd}` with the following error:\n"
        f"```\n{test_output[-1500:]}\n```\n"
        f"Please inspect the failure and produce the corrected SEARCH/REPLACE block to make the test pass."
    )

    res_retry: ImplementResult = asyncio.run(
        implementer.implement(target_path=target_path, instruction=retry_instruction, apply=apply)
    )

    if res_retry.diff.strip():
        print(f"\n📄 Unified Diff (Attempt 2):\n{res_retry.diff}\n")

    passed_retry, retry_test_output = run_test_command(test_cmd)
    if passed_retry:
        print(f"✅ Verification PASSED on Attempt 2! `{target_path.name}` successfully resolved.")
        return 0

    # Both attempts failed
    print("\n❌ Verification still FAILED after 2 attempts.")
    print(f"Output:\n{retry_test_output[-400:]}\n")

    # Rollback to pre-fix backup if available
    bak_path = target_path.with_suffix(f"{target_path.suffix}.vifi_bak")
    if bak_path.exists():
        print(f"⏪ Rolling back `{target_path.name}` to original state from backup...")
        shutil.copy2(bak_path, target_path)

    print("🛑 Escalate to Antigravity: Local model could not resolve the test within 2 turns.")
    return 2
