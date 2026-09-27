"""
Unit tests for /api/fix and /vifi/fix endpoints on Companion Server.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from aiohttp import web
from pathlib import Path

from voicefi.companion.server import CompanionServer
from voicefi.local.implementer import ImplementResult


@pytest.mark.anyio
async def test_handle_api_fix_success(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("x = 1")

    mock_result = ImplementResult(
        target_path=str(target),
        instruction="Change x to 2",
        diff="+x = 2",
        applied=True,
        scout_duration=0.1,
        coder_duration=0.5,
        total_duration=0.6,
        tokens_saved=50,
        savings_pct=80.0,
        input_tokens_est=60,
        diff_tokens_est=10,
        model_scout="gemma4-2b",
        model_coder="gemma4-26b",
    )

    with patch("voicefi.companion.server.CompanionServer._setup_routes"):
        server = CompanionServer.__new__(CompanionServer)

        mock_req = MagicMock(spec=web.Request)
        mock_req.json = AsyncMock(return_value={
            "target": str(target),
            "error": "Change x to 2",
            "apply": True,
        })

        with patch("voicefi.local.implementer.ReconImplementer") as mock_impl_cls:
            instance = MagicMock()
            instance.implement = AsyncMock(return_value=mock_result)
            mock_impl_cls.return_value = instance

            resp = await server.handle_api_fix(mock_req)
            assert resp.status == 200


@pytest.mark.anyio
async def test_handle_api_fix_file_not_found():
    with patch("voicefi.companion.server.CompanionServer._setup_routes"):
        server = CompanionServer.__new__(CompanionServer)

        mock_req = MagicMock(spec=web.Request)
        mock_req.json = AsyncMock(return_value={
            "target": "/nonexistent/path/to/fake_file.py",
            "error": "syntax error",
        })

        resp = await server.handle_api_fix(mock_req)
        assert resp.status == 404
