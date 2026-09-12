"""
Comprehensive Unit & Integration Test Suite for VoiceFi's Obsidian Voice-to-Vault Bridge.
Validates:
1. Universal Obsidian Vault Discovery on macOS.
2. Direct Voice-to-Vault Quick Capture (atomic append to today's daily note, 0-latency, 100% offline).
3. Voice Memo Buffer & Auto-Structuring (Voice Memos/ + Daily Note backlinking).
4. MCP Server Tools: voicefi_vault_append, voicefi_vault_query, voicefi_vault_memo.
5. Companion Server REST Endpoints (/api/vault/capture, /api/vault/memo, /api/vault/today, /api/vault/status).
6. Universal Agent Launch (both Antigravity and Claude Code).
"""

import datetime
import json
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
import asyncio
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from voicefi.config import VoiceFiConfig
from voicefi.integrations.obsidian import (
    find_obsidian_vaults,
    get_primary_vault,
    get_daily_note_path,
    append_quick_capture_to_vault,
    save_memo_to_vault,
    get_today_note_content,
    is_obsidian_installed,
    is_plugin_installed,
    launch_agent_in_vault,
)
from voicefi.mcp_server import VoiceFiMCPServer
from voicefi.companion.server import CompanionServer


def test_obsidian_vault_discovery(tmp_path):
    """Test discovering registered vaults and falling back to default."""
    cfg = VoiceFiConfig()
    cfg.obsidian.vault_path = str(tmp_path)
    primary = get_primary_vault(cfg)
    assert primary == tmp_path


def test_daily_note_path_resolution(tmp_path):
    """Test daily note path resolution with default and custom configurations."""
    vault = tmp_path / "TestVault"
    vault.mkdir()
    today = datetime.date(2026, 9, 10)

    # 1. Default root resolution
    path = get_daily_note_path(vault, today=today)
    assert path == vault / "2026-09-10.md"

    # 2. Daily Notes subdirectory if present
    daily_folder = vault / "Daily Notes"
    daily_folder.mkdir()
    path2 = get_daily_note_path(vault, today=today)
    assert path2 == daily_folder / "2026-09-10.md"

    # 3. Custom config folder
    cfg = VoiceFiConfig()
    cfg.obsidian.daily_note_folder = "Journal"
    path3 = get_daily_note_path(vault, today=today, config=cfg)
    assert path3 == vault / "Journal" / "2026-09-10.md"
    assert (vault / "Journal").is_dir()


def test_quick_capture_atomic_append(tmp_path):
    """Test direct voice quick capture creates and appends to today's daily note."""
    vault = tmp_path / "MyVault"
    vault.mkdir()

    now = datetime.datetime(2026, 9, 10, 14, 30)
    ts = now.timestamp()

    # First append creates daily note
    res1 = append_quick_capture_to_vault(
        text="Reviewing auth refactoring in VoiceFi daemon",
        vault_path=vault,
        timestamp=ts,
    )
    assert res1["status"] == "ok"
    assert res1["vault_name"] == "MyVault"
    assert "14:30" in res1["time"] or "2:30" in res1["time"]

    daily_note = Path(res1["daily_note_path"])
    assert daily_note.is_file()
    content1 = daily_note.read_text(encoding="utf-8")
    assert "# 2026-09-10" in content1
    assert "Reviewing auth refactoring in VoiceFi daemon" in content1

    # Second append adds to existing note
    now2 = datetime.datetime(2026, 9, 10, 14, 45)
    res2 = append_quick_capture_to_vault(
        text="Second thought: test push-to-talk on companion",
        vault_path=vault,
        timestamp=now2.timestamp(),
    )
    assert res2["status"] == "ok"
    content2 = daily_note.read_text(encoding="utf-8")
    assert "Reviewing auth refactoring in VoiceFi daemon" in content2
    assert "Second thought: test push-to-talk on companion" in content2


def test_save_memo_to_vault_and_backlink(tmp_path):
    """Test saving structured memo spec to Voice Memos/ and creating backlink in daily note."""
    vault = tmp_path / "MemoVault"
    vault.mkdir()
    today = datetime.date(2026, 9, 10)

    memo_body = """# Multi-Agent Architecture
> Spoken memo captured on 2026-09-10

## Architecture
```mermaid
graph TD
    A[Antigravity] --> B[VoiceFi Daemon]
    B --> C[Claude Code]
```
## Checklist
- [ ] Test cross-agent bridge
"""

    res = save_memo_to_vault(
        memo_markdown=memo_body,
        title="Multi-Agent Architecture",
        vault_path=vault,
        today=today,
    )
    assert res["status"] == "ok"
    assert res["memo_name"] == "2026-09-10 - Multi-Agent Architecture.md"

    memo_file = Path(res["memo_path"])
    assert memo_file.is_file()
    assert "Multi-Agent Architecture" in memo_file.read_text(encoding="utf-8")

    # Verify backlink in daily note
    daily_file = Path(res["daily_note_path"])
    assert daily_file.is_file()
    daily_content = daily_file.read_text(encoding="utf-8")
    assert "[[2026-09-10 - Multi-Agent Architecture]]" in daily_content


def test_get_today_note_content(tmp_path):
    """Test querying today's daily note content."""
    vault = tmp_path / "QueryVault"
    vault.mkdir()

    # When note does not exist
    res1 = get_today_note_content(vault_path=vault)
    assert res1["status"] == "ok"
    assert res1["exists"] is False

    # After appending note
    append_quick_capture_to_vault("First capture of the day", vault_path=vault)
    res2 = get_today_note_content(vault_path=vault)
    assert res2["status"] == "ok"
    assert res2["exists"] is True
    assert "First capture of the day" in res2["content"]


def test_mcp_server_vault_tools(tmp_path):
    """Test VoiceFi MCP server vault tools dispatch and output."""
    vault = tmp_path / "MCPVault"
    vault.mkdir()

    server = VoiceFiMCPServer()

    # 1. voicefi_vault_append
    append_resp = server.execute_tool(
        "voicefi_vault_append",
        {"text": "MCP appended note item", "vault_path": str(vault)},
    )
    assert append_resp.get("isError") is False
    assert "Appended to Obsidian Daily Note" in append_resp["content"][0]["text"]

    # 2. voicefi_vault_query
    query_resp = server.execute_tool(
        "voicefi_vault_query",
        {"vault_path": str(vault)},
    )
    assert query_resp.get("isError") is False
    assert "MCP appended note item" in query_resp["content"][0]["text"]

    # 3. voicefi_vault_memo
    memo_resp = server.execute_tool(
        "voicefi_vault_memo",
        {
            "title": "MCP Spec",
            "markdown": "# MCP Spec\nDetails here",
            "vault_path": str(vault),
        },
    )
    assert memo_resp.get("isError") is False
    assert "Saved Voice Memo" in memo_resp["content"][0]["text"]

    # 4. Error validation: missing required params
    err_resp = server.execute_tool("voicefi_vault_append", {"text": ""})
    assert err_resp.get("isError") is True


def test_universal_agent_launch(tmp_path):
    """Test launching both Antigravity and Claude Code rooted in vault."""
    vault = tmp_path / "AgentVault"
    vault.mkdir()

    with patch("subprocess.run") as mock_run:
        res_claude = launch_agent_in_vault(engine="claude", vault_path=vault)
        assert res_claude["status"] == "ok"
        assert res_claude["engine"] == "claude"
        mock_run.assert_called_once()

    with patch(
        "voicefi.integrations.injector.create_new_antigravity_conversation",
        return_value="test-conv-123",
    ):
        res_agy = launch_agent_in_vault(engine="antigravity", vault_path=vault)
        assert res_agy["status"] == "ok"
        assert res_agy["engine"] == "antigravity"
        assert res_agy["conv_id"] == "test-conv-123"


class CompanionVaultTestCase(AioHTTPTestCase):
    """Test Companion HTTP endpoints for Obsidian Vault integration."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.test_vault = self.cfg.obsidian.vault_path = "/tmp/voicefi_test_companion_vault"
        Path(self.test_vault).mkdir(parents=True, exist_ok=True)
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    @unittest_run_loop
    async def test_api_vault_endpoints(self):
        # 1. Test POST /api/vault/capture
        cap_resp = await self.client.post(
            "/api/vault/capture",
            json={"text": "Companion quick capture note", "vault_path": self.test_vault},
        )
        assert cap_resp.status == 200
        data = await cap_resp.json()
        assert data["status"] == "ok"
        assert "Companion quick capture note" in data["entry"]

        # 2. Test GET /api/vault/today
        today_resp = await self.client.get(
            f"/api/vault/today?vault_path={self.test_vault}"
        )
        assert today_resp.status == 200
        tdata = await today_resp.json()
        assert tdata["exists"] is True
        assert "Companion quick capture note" in tdata["content"]

        # 3. Test GET /api/vault/status
        status_resp = await self.client.get("/api/vault/status")
        assert status_resp.status == 200
        sdata = await status_resp.json()
        assert sdata["status"] == "ok"

        # 4. Test POST /api/send with engine="obsidian"
        send_resp = await self.client.post(
            "/api/send",
            json={"text": "Note sent through universal send endpoint", "engine": "obsidian"},
        )
        assert send_resp.status == 200
        s_data = await send_resp.json()
        assert s_data["success"] is True
        assert s_data["engine"] == "obsidian"

        # 5. Test POST /api/vault/memo with raw_text
        memo_resp = await self.client.post(
            "/api/vault/memo",
            json={
                "raw_text": "We need to build a robust local audio pipeline with full duplex barge in.",
                "vault_path": self.test_vault,
            },
        )
        assert memo_resp.status == 200
        m_data = await memo_resp.json()
        assert m_data["status"] == "ok"
        assert "memo_name" in m_data
        assert Path(m_data["memo_path"]).is_file()


# ---------------------------------------------------------------------------
# Vault-wide retrieval (VaultAgent search layer)
# ---------------------------------------------------------------------------


def _seed_vault(tmp_path):
    """Build a small vault with a distinctive fact in one note among decoys."""
    vault = tmp_path / "SearchVault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "plugin.md").write_text("lien pipeline decoy in config", encoding="utf-8")
    (vault / "Lien Pipeline.md").write_text(
        "# Lien Pipeline\n\nWe decided to batch the lien filings weekly.\n"
        "The cutoff is Thursday at noon.\n",
        encoding="utf-8",
    )
    (vault / "Groceries.md").write_text("- milk\n- eggs\n", encoding="utf-8")
    (vault / "Standup.md").write_text("The pipeline is fine. Nothing to report.\n", encoding="utf-8")
    return vault


def test_search_vault_ranks_relevant_note_first(tmp_path):
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _seed_vault(tmp_path)
    hits = VaultAgent().search_vault("what did we decide about the lien filings", vault_path=vault)

    assert hits, "expected at least one hit"
    assert hits[0]["note"] == "Lien Pipeline"
    assert "batch the lien filings weekly" in hits[0]["snippet"]


def test_search_vault_excludes_obsidian_config_dir(tmp_path):
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _seed_vault(tmp_path)
    hits = VaultAgent().search_vault("lien pipeline", vault_path=vault)

    assert all(".obsidian" not in h["path"] for h in hits)


def test_search_vault_empty_on_stopword_only_query(tmp_path):
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _seed_vault(tmp_path)
    assert VaultAgent().search_vault("what about the", vault_path=vault) == []


def test_python_scan_matches_ripgrep_results(tmp_path):
    """The no-ripgrep fallback must find the same note as the rg path."""
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _seed_vault(tmp_path)
    agent = VaultAgent()
    terms = agent.extract_search_terms("lien filings cutoff")

    rg_hits = agent._ripgrep(terms, vault)
    py_hits = agent._python_scan(terms, vault)

    py_files = {h[0] for h in py_hits}
    assert any("Lien Pipeline.md" in f for f in py_files)
    if rg_hits is not None:  # ripgrep present in this environment
        assert {h[0] for h in rg_hits} == py_files


def test_answer_falls_back_to_retrieval_without_llm(tmp_path, monkeypatch):
    """With no LLM provider, the answer reads the snippet and names the note."""
    from voicefi.integrations import vault_agent as va

    vault = _seed_vault(tmp_path)
    agent = va.VaultAgent()
    monkeypatch.setattr(agent, "_synthesize_answer", lambda *a, **k: None)

    res = agent.answer_vault_query("when is the lien filing cutoff", vault_path=vault)

    assert res["provider"] == "retrieval"
    assert "Lien Pipeline" in res["spoken_response"]
    assert res["sources"][0]["note"] == "Lien Pipeline"


def test_answer_reports_nothing_found(tmp_path):
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _seed_vault(tmp_path)
    res = VaultAgent().answer_vault_query("what about quantum entanglement rigs", vault_path=vault)

    assert res["sources"] == []
    assert res["provider"] == "none"
    assert "found nothing" in res["spoken_response"]


def test_spoken_answer_strips_markdown(tmp_path):
    from voicefi.integrations.vault_agent import VaultAgent

    vault = tmp_path / "MdVault"
    vault.mkdir()
    (vault / "Deploy.md").write_text(
        "# Deploy\n\n- **Step one:** run `make ship` see [docs](http://x.com) and [[Runbook]]\n",
        encoding="utf-8",
    )
    res = VaultAgent().answer_vault_query("what are the deploy steps", vault_path=vault)

    spoken = res["spoken_response"]
    for junk in ("**", "`", "[[", "](", "#"):
        assert junk not in spoken, f"{junk!r} leaked into spoken answer: {spoken}"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("what did I decide about the lien pipeline?", True),
        ("remind me what the deploy steps were", True),
        ("how does the audio mutex work", True),
        ("where did I put the checkout link", True),
        ("Need to call the title company tomorrow", False),
        ("Idea: route memos through the relay", False),
        ("ship the vertical cut by friday", False),
        ("what a mess", False),
        ("how annoying", False),
        ("", False),
    ],
)
def test_is_vault_question_routing(text, expected):
    from voicefi.integrations.vault_agent import is_vault_question

    assert is_vault_question(text) is expected


# ---------------------------------------------------------------------------
# Secret redaction at the snippet boundary
# ---------------------------------------------------------------------------


def _secret_vault(tmp_path):
    vault = tmp_path / "SecretVault"
    vault.mkdir()
    (vault / "Billing.md").write_text(
        "# Billing\n\n"
        "Stripe webhook signing secret whsec_tRS7ZqBXW6Oml046coxKpyc4yTIW3fh\n"
        "RESEND_API_KEY re_drwGJa6B_2XBUjK7mQpLxvNa9ZqW\n"
        "Invoices go out on the first of the month.\n",
        encoding="utf-8",
    )
    return vault


def test_snippets_are_redacted_at_creation(tmp_path):
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _secret_vault(tmp_path)
    hits = VaultAgent().search_vault("stripe webhook signing secret", vault_path=vault)

    assert hits, "expected the billing note to match"
    blob = " ".join(h["snippet"] for h in hits)
    assert "whsec_tRS7" not in blob
    assert "re_drwGJa6B" not in blob
    assert "[redacted]" in blob


def test_spoken_answer_never_contains_secret(tmp_path):
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _secret_vault(tmp_path)
    res = VaultAgent().answer_vault_query("what is the webhook signing secret", vault_path=vault)

    assert "whsec_tRS7" not in res["spoken_response"]
    assert "whsec_tRS7" not in res["matched_snippet"]


def test_redaction_preserves_surrounding_prose(tmp_path):
    """Masking a secret must not destroy the note's readable context."""
    from voicefi.integrations.vault_agent import VaultAgent

    vault = _secret_vault(tmp_path)
    res = VaultAgent().answer_vault_query("when do invoices go out", vault_path=vault)

    assert "Billing" in res["spoken_response"]


def test_llm_context_is_redacted_even_if_hits_bypass_choke_point(tmp_path, monkeypatch):
    """A caller hand-building hits must still not leak into the LLM call."""
    from voicefi.integrations import vault_agent as va

    sent = {}

    class _FakeEngine:
        def __init__(self, *a, **k):
            pass

        def is_available(self):
            return True

        def generate_completion(self, prompt, **kwargs):
            sent["prompt"] = prompt
            return "Invoices go out on the first."

    monkeypatch.setattr(
        "voicefi.integrations.gemini_ai.GeminiIntelligenceEngine", _FakeEngine
    )

    agent = va.VaultAgent()
    raw_hits = [
        {
            "note": "Billing",
            "path": "/tmp/Billing.md",
            "line": 3,
            "snippet": "RESEND_API_KEY re_drwGJa6B_2XBUjK7mQpLxvNa9ZqW",
            "matched_terms": ["resend"],
            "score": 10.0,
        }
    ]
    agent._synthesize_answer("what is the resend key", raw_hits)

    assert "prompt" in sent, "expected the LLM to be called"
    assert "re_drwGJa6B" not in sent["prompt"]
    assert "[redacted]" in sent["prompt"]
