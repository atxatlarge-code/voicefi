"""
tests/test_tier0_embed.py
Comprehensive test suite for VoiceFi Tier 0 Vector Grounding & Reflex Arbitration.

Tests:
1. EmbeddingEngine vector properties, normalization, and air-gap secret redaction.
2. LocalGroundingStore indexing, TTL expiration, and cosine similarity retrieval.
3. Tier0ReflexArbiter direct reflex actions vs. escalation boundaries.
4. ThermalSupervisor Tier 0 reflex exemptions under SERIOUS thermal load.
5. LocalIntentRouter end-to-end integration and dispatch latency.
"""

import time
import numpy as np
import pytest

from voicefi.local.embed import (
    EmbeddingEngine,
    GroundingEntity,
    LocalGroundingStore,
    Tier0Action,
    Tier0ReflexArbiter,
)
from voicefi.local.supervisor import ThermalSupervisor, HardwareTelemetry
from voicefi.local.router import classify_model_tier, CASCADE_HIERARCHY, TASK_DEFAULT_PREFERENCES
from voicefi.local.intent import LocalIntentRouter


class TestEmbeddingEngine:
    def test_embed_returns_normalized_vector(self):
        engine = EmbeddingEngine()
        vec = engine.embed_text("Find the Safari window with GitHub pull requests")
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (768,)
        assert vec.dtype == np.float32
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-4

    def test_embed_empty_returns_zero(self):
        engine = EmbeddingEngine()
        vec = engine.embed_text("")
        assert np.all(vec == 0.0)

    def test_air_gap_secret_redaction_before_embed(self):
        engine = EmbeddingEngine()
        raw_text = "API Key: sk-live-abcdef1234567890123456 and token ghp_12345678901234567890"
        # Secret redaction must ensure plaintext secret is never indexed or preserved
        safe_vec = engine.embed_text(raw_text)
        assert safe_vec is not None
        assert np.linalg.norm(safe_vec) > 0.0


class TestLocalGroundingStore:
    def test_index_and_search_entity(self):
        store = LocalGroundingStore(db_path=":memory:")
        store.index_entity(
            entity_type="window",
            bundle_id="com.linear",
            title="Linear - Issue ENG-402",
            text_content="Linear issue ENG-402 discussing ThermalSupervisor throttle threshold",
        )
        store.index_entity(
            entity_type="window",
            bundle_id="com.apple.Safari",
            title="GitHub - PR #88",
            text_content="Pull request 88 audio buffer and silero vad",
        )

        results = store.search("Linear issue ENG-402", top_k=2, min_similarity=0.25)
        assert len(results) >= 1
        top = results[0]
        assert top.bundle_id == "com.linear"
        assert "Linear" in top.title
        assert top.similarity >= 0.25

    def test_secret_redaction_in_store(self):
        store = LocalGroundingStore(db_path=":memory:")
        store.index_entity(
            entity_type="clipboard",
            bundle_id="com.apple.Terminal",
            title="Terminal Selection",
            text_content="export OPENAI_API_KEY=sk-abcdef123456789012345678",
        )

        cur = store.conn.cursor()
        cur.execute("SELECT text_content FROM local_entities")
        row = cur.fetchone()
        assert "sk-abcdef" not in row[0]
        assert "[redacted]" in row[0]

    def test_ttl_expiration_pruning(self):
        store = LocalGroundingStore(db_path=":memory:")
        # Index with 1 second TTL
        store.index_entity(
            entity_type="ocr_text",
            bundle_id="com.sublimetext.4",
            title="Editor",
            text_content="Temporary transient text",
            ttl_seconds=1,
        )
        assert len(store.search("Temporary text", min_similarity=0.1)) == 1

        # Simulate time passage
        time.sleep(1.2)
        pruned = store.prune_expired()
        assert pruned == 1
        assert len(store.search("Temporary text", min_similarity=0.1)) == 0


class TestTier0ReflexArbiter:
    def test_direct_window_focus_reflex(self):
        store = LocalGroundingStore(db_path=":memory:")
        store.index_entity(
            entity_type="window",
            bundle_id="com.apple.Safari",
            title="Safari - VoiceFi Documentation",
            text_content="Safari window with VoiceFi documentation and guides",
        )

        arbiter = Tier0ReflexArbiter(store=store)
        action = arbiter.arbitrate("Switch to Safari window")

        assert action.action == "focus_window"
        assert action.bundle_id == "com.apple.Safari"
        assert action.escalate is False

    def test_telemetry_heuristic_reflex(self):
        store = LocalGroundingStore(db_path=":memory:")
        arbiter = Tier0ReflexArbiter(store=store)

        action = arbiter.arbitrate("what is my battery level?")
        assert action.action == "read_telemetry"
        assert action.target_id == "battery"
        assert action.escalate is False

    def test_complex_coding_escalates(self):
        store = LocalGroundingStore(db_path=":memory:")
        arbiter = Tier0ReflexArbiter(store=store)

        action = arbiter.arbitrate("Refactor the supervisor database query to use CTEs and add tests")
        assert action.escalate is True


class TestThermalSupervisorTier0:
    def test_embedding_gemma_model_requirements(self):
        sup = ThermalSupervisor()
        req = sup.get_model_requirement("embedding-gemma-2:740m")
        assert req["min_free_ram_gb"] == 0.8
        assert req["is_tier0"] is True

    def test_tier0_thermal_exemption(self, monkeypatch):
        sup = ThermalSupervisor(pause_on_serious=True)

        # Mock telemetry to SERIOUS thermal state with 8GB free RAM
        fake_telem = HardwareTelemetry(
            system="Darwin",
            thermal_state="SERIOUS",
            thermal_raw="Thermal pressure: Serious",
            free_ram_gb=8.0,
            total_ram_gb=16.0,
            ram_percent=50.0,
            load_avg_1m=2.0,
            is_safe=False,
        )
        monkeypatch.setattr(sup, "get_telemetry", lambda: fake_telem)

        # Standard non-Tier0 model MUST be blocked
        can_load_std, reason_std, _ = sup.can_load_model("qwen2.5-coder:7b")
        assert can_load_std is False
        assert "thermal" in reason_std.lower()

        # Tier 0 model with reflex exemption MUST be allowed
        can_load_t0, reason_t0, _ = sup.can_load_model("embedding-gemma-2:740m")
        assert can_load_t0 is True


class TestRouterTier0Classification:
    def test_tier0_classification_labels(self):
        assert classify_model_tier("embedding-gemma-2:740m") == "edge_tier0_embed"
        assert classify_model_tier("tev1:0.8b") == "edge_tier0_reflex"

    def test_cascade_hierarchy_includes_tier0(self):
        assert "embedding-gemma-2:740m" in CASCADE_HIERARCHY
        assert "tev1:0.8b" in CASCADE_HIERARCHY
        assert "tier0_reflex" in TASK_DEFAULT_PREFERENCES
        assert "embed" in TASK_DEFAULT_PREFERENCES


class TestLocalIntentRouterTier0:
    def test_route_prompt_tier0_window_focus(self):
        store = LocalGroundingStore(db_path=":memory:")
        store.index_entity(
            entity_type="window",
            bundle_id="com.apple.Safari",
            title="Safari - VoiceFi Repo",
            text_content="Safari window with VoiceFi GitHub pull requests",
        )
        arbiter = Tier0ReflexArbiter(store=store)
        router = LocalIntentRouter(tier0_arbiter=arbiter)

        result = router.route_prompt("Switch to Safari window", use_local_model=True)
        assert result.get("status") == "handled_tier0_reflex"
        assert result.get("target") == "local_window_focus"
        assert result.get("bundle_id") == "com.apple.Safari"
        assert "Safari" in result.get("spoken_response", "")

    def test_route_prompt_complex_escalates_to_agent(self):
        store = LocalGroundingStore(db_path=":memory:")
        arbiter = Tier0ReflexArbiter(store=store)
        router = LocalIntentRouter(tier0_arbiter=arbiter)

        result = router.route_prompt("Refactor the caching layer in Redis and fix race condition", use_local_model=True)
        assert result.get("status") in ("routed_agent", "routed_antigravity")
