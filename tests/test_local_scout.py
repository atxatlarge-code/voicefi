"""
Unit tests for VoiceFi Recon Scout and token savings calculation.
"""

import asyncio
from pathlib import Path
from voicefi.local.scout import ReconScout, ScoutResult, estimate_tokens


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") >= 1
    # 400 characters ~ 100 tokens
    assert 90 <= estimate_tokens("a" * 400) <= 110


def test_recon_scout_on_file(tmp_path: Path):
    test_file = tmp_path / "sample_service.py"
    test_file.write_text(
        "import os\n"
        "def authenticate_user():\n"
        "    try:\n"
        "        token = os.environ['AUTH_TOKEN']\n"
        "    except KeyError as e:\n"
        "        raise Exception('CRITICAL: Missing AUTH_TOKEN environment variable')\n"
    )

    scout = ReconScout()
    scout.engine.model_path = str(tmp_path / "nonexistent_model")
    res = asyncio.run(scout.scout(target_path=test_file, query="Identify critical exceptions"))

    assert isinstance(res, ScoutResult)
    assert res.target == str(test_file)
    assert res.error is None
    assert "CRITICAL: Missing AUTH_TOKEN" in res.findings
    assert res.input_tokens_est > 0
    assert res.output_tokens > 0
    assert res.duration_seconds >= 0.0


def test_recon_scout_missing_file():
    scout = ReconScout()
    res = asyncio.run(scout.scout(target_path="/nonexistent/path/file.log"))
    assert res.error is not None
    assert "does not exist" in res.error
