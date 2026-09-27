"""
Unit tests for VoiceFi ReconImplementer and on-device model routing.
Ensures port 9379 is strictly dedicated to gemma4-2b, while gemma4-26b routes
directly to in-process LocalModelEngine to prevent model-swapping CPU thrash.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from voicefi.local.implementer import (
    apply_search_replace,
    parse_search_replace_blocks,
    query_model,
    ReconImplementer,
    ImplementResult,
    LOCAL_SERVER_URL,
)


def test_apply_search_replace_exact():
    original = "def foo():\n    return 42\n"
    search = "return 42"
    replace = "return 100"
    res, applied = apply_search_replace(original, search, replace)
    assert applied is True
    assert "return 100" in res


def test_apply_search_replace_whitespace_tolerant():
    original = "def foo():\n    x = 1\n    y = 2\n    return x + y\n"
    search = "x = 1\ny = 2"
    replace = "x = 10\ny = 20"
    res, applied = apply_search_replace(original, search, replace)
    assert applied is True
    assert "x = 10" in res


def test_apply_search_replace_no_match():
    original = "def foo():\n    return 42\n"
    search = "def nonexistent():\n    pass"
    replace = "def replacement():\n    pass"
    res, applied = apply_search_replace(original, search, replace)
    assert applied is False
    assert res == original


def test_parse_search_replace_blocks():
    text = (
        "Here is the diff:\n"
        "<<<<<<< SEARCH\n"
        "old_func()\n"
        "=======\n"
        "new_func()\n"
        ">>>>>>> REPLACE\n"
        "And another:\n"
        "<<<<<<< SEARCH\n"
        "val = 1\n"
        "=======\n"
        "val = 2\n"
        ">>>>>>> REPLACE\n"
    )
    blocks = parse_search_replace_blocks(text)
    assert len(blocks) == 2
    assert blocks[0] == ("old_func()", "new_func()")
    assert blocks[1] == ("val = 1", "val = 2")


@pytest.mark.anyio
async def test_query_model_gemma4_2b_uses_http():
    """Verify gemma4-2b uses the warm HTTP endpoint at port 9379."""
    mock_resp_data = {
        "choices": [{"message": {"content": "2B fast response"}}]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen, \
         patch("voicefi.local.implementer.LocalModelEngine") as mock_engine_cls:
        res = await query_model(
            model_name="gemma4-2b",
            prompt="summarize this",
            system_prompt="system instructions",
        )
        assert res == "2B fast response"
        assert mock_urlopen.called
        assert not mock_engine_cls.called


@pytest.mark.anyio
async def test_query_model_gemma4_26b_uses_http():
    """Verify gemma4-26b uses warm HTTP endpoint when available."""
    mock_resp_data = {
        "choices": [{"message": {"content": "26B fast response"}}]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen, \
         patch("voicefi.local.implementer.LocalModelEngine") as mock_engine_cls:
        res = await query_model(
            model_name="gemma4-26b",
            prompt="write code",
            system_prompt="coder instructions",
        )
        assert res == "26B fast response"
        assert mock_urlopen.called
        assert not mock_engine_cls.called



@pytest.mark.anyio
async def test_query_model_gemma4_2b_fallback_to_engine_on_http_error():
    """Verify gemma4-2b falls back to LocalModelEngine if HTTP server fails."""
    mock_engine = MagicMock()
    mock_engine.chat_text = AsyncMock(return_value="Engine fallback response")

    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")), \
         patch("voicefi.local.implementer.LocalModelEngine", return_value=mock_engine):
        res = await query_model(
            model_name="gemma4-2b",
            prompt="summarize this",
        )
        assert res == "Engine fallback response"


@pytest.mark.anyio
async def test_recon_implementer_nonexistent_file(tmp_path):
    implementer = ReconImplementer()
    fake_file = tmp_path / "does_not_exist.py"
    result = await implementer.implement(target_path=fake_file, instruction="Fix bug")
    assert result.applied is False
    assert result.error is not None
    assert "File not found" in result.error


@pytest.mark.anyio
async def test_recon_implementer_e2e_mocked(tmp_path):
    """Test 2-tier implementer cascade with simulated scout and coder outputs."""
    target_file = tmp_path / "app.py"
    target_file.write_text("def run():\n    return False\n", encoding="utf-8")

    scout_reply = "Lines 1-2: return False needs to be updated to True"
    coder_reply = (
        "<<<<<<< SEARCH\n"
        "def run():\n    return False\n"
        "=======\n"
        "def run():\n    return True\n"
        ">>>>>>> REPLACE"
    )

    async def mock_query(model_name, prompt, system_prompt=None, max_tokens=2048, temperature=0.2):
        if model_name == "gemma4-2b":
            return scout_reply
        return coder_reply

    with patch("voicefi.local.implementer.query_model", side_effect=mock_query):
        implementer = ReconImplementer(model_scout="gemma4-2b", model_coder="gemma4-26b")
        result = await implementer.implement(target_path=target_file, instruction="Make run return True")

        assert result.applied is True
        assert result.error is None
        assert "return True" in target_file.read_text(encoding="utf-8")
        assert "+    return True" in result.diff
        assert "-    return False" in result.diff
