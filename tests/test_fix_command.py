"""
Unit tests for vifi fix command and self-healing verification loop.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import argparse

from voicefi.cli_commands.fix import cmd_fix
from voicefi.local.implementer import ImplementResult


def make_mock_result(target_path, diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-x=1\n+x=2", applied=True, error=None):
    return ImplementResult(
        target_path=str(target_path),
        instruction="Fix bug",
        diff=diff,
        applied=applied,
        scout_duration=0.5,
        coder_duration=1.2,
        total_duration=1.7,
        tokens_saved=100,
        savings_pct=85.0,
        input_tokens_est=120,
        diff_tokens_est=20,
        model_scout="gemma4-2b",
        model_coder="gemma4-26b",
        error=error,
    )


def test_cmd_fix_direct_file(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("x = 1")

    args = argparse.Namespace(
        target=str(target),
        error="x should be 2",
        instruction=None,
        clip=False,
        test=None,
        apply=True,
        model_scout="gemma4-2b",
        model_coder="gemma4-26b",
    )

    mock_res = make_mock_result(target)
    with patch("voicefi.cli_commands.fix.ReconImplementer") as mock_impl_cls:
        instance = MagicMock()
        instance.implement = AsyncMock(return_value=mock_res)
        mock_impl_cls.return_value = instance

        ret = cmd_fix(args)
        assert ret == 0
        instance.implement.assert_awaited_once()


def test_cmd_fix_traceback_extraction(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("def div(a, b): return a / b")

    trace = f"""
Traceback (most recent call last):
  File "{target}", line 1, in div
    return a / b
ZeroDivisionError: division by zero
"""
    args = argparse.Namespace(
        target=None,
        error=trace,
        instruction=None,
        clip=False,
        test=None,
        apply=True,
        model_scout="gemma4-2b",
        model_coder="gemma4-26b",
    )

    mock_res = make_mock_result(target)
    with patch("voicefi.cli_commands.fix.ReconImplementer") as mock_impl_cls:
        instance = MagicMock()
        instance.implement = AsyncMock(return_value=mock_res)
        mock_impl_cls.return_value = instance

        ret = cmd_fix(args)
        assert ret == 0
        call_kwargs = instance.implement.call_args.kwargs
        assert str(call_kwargs["target_path"]) == str(target.resolve())
        assert "ZeroDivisionError" in call_kwargs["instruction"]


def test_cmd_fix_self_healing_attempt_2_success(tmp_path):
    target = tmp_path / "calc.py"
    target.write_text("x = 0")

    args = argparse.Namespace(
        target=str(target),
        error="fix value",
        instruction=None,
        clip=False,
        test="pytest check",
        apply=True,
        model_scout="gemma4-2b",
        model_coder="gemma4-26b",
    )

    mock_res1 = make_mock_result(target, diff="+x=1")
    mock_res2 = make_mock_result(target, diff="+x=2")

    with patch("voicefi.cli_commands.fix.ReconImplementer") as mock_impl_cls, \
         patch("voicefi.cli_commands.fix.run_test_command") as mock_test_cmd:

        instance = MagicMock()
        # Attempt 1 returns mock_res1, Attempt 2 returns mock_res2
        instance.implement = AsyncMock(side_effect=[mock_res1, mock_res2])
        mock_impl_cls.return_value = instance

        # Test fails on Attempt 1, passes on Attempt 2
        mock_test_cmd.side_effect = [
            (False, "AssertionError: expected 2 got 1"),
            (True, "All tests passed"),
        ]

        ret = cmd_fix(args)
        assert ret == 0
        assert instance.implement.await_count == 2
        assert mock_test_cmd.call_count == 2


def test_cmd_fix_failure_rolls_back(tmp_path):
    target = tmp_path / "calc.py"
    target.write_text("ORIGINAL_CONTENT")
    bak = tmp_path / "calc.py.vifi_bak"
    bak.write_text("ORIGINAL_CONTENT")

    args = argparse.Namespace(
        target=str(target),
        error="fix value",
        instruction=None,
        clip=False,
        test="pytest check",
        apply=True,
        model_scout="gemma4-2b",
        model_coder="gemma4-26b",
    )

    mock_res = make_mock_result(target)

    with patch("voicefi.cli_commands.fix.ReconImplementer") as mock_impl_cls, \
         patch("voicefi.cli_commands.fix.run_test_command") as mock_test_cmd:

        instance = MagicMock()
        instance.implement = AsyncMock(return_value=mock_res)
        mock_impl_cls.return_value = instance

        # Both attempts fail tests
        mock_test_cmd.return_value = (False, "Still failing")

        # Simulate local model modifying file to BAD_CONTENT
        target.write_text("BAD_CONTENT")

        ret = cmd_fix(args)
        # Should return 2 (escalate) and rollback target to ORIGINAL_CONTENT
        assert ret == 2
        assert target.read_text() == "ORIGINAL_CONTENT"
