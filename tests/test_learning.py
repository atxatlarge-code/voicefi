"""
Unit tests for VoiceFi Recursive Self-Learning Engine (Phonetic & Brevity).
"""

import os
import json
import pytest
from pathlib import Path
from voicefi.learning.phonetic import PhoneticLearner
from voicefi.learning.brevity import BrevityLearner
from voicefi.tts.normalizer import normalize_stt_text, normalize_tts_text
from voicefi.stt.biasing import PhoneticNormalizer


@pytest.fixture
def temp_learning_env(tmp_path):
    """Fixture providing isolated temporary paths for learning memory."""
    mem_path = tmp_path / "phonetic_memory.json"
    cog_path = tmp_path / "cognitive_profile.json"
    
    p_learner = PhoneticLearner(memory_path=mem_path)
    b_learner = BrevityLearner(profile_path=cog_path)
    
    old_p_instance = PhoneticLearner._instance
    old_b_instance = BrevityLearner._instance
    PhoneticLearner._instance = p_learner
    BrevityLearner._instance = b_learner
    
    yield p_learner, b_learner, tmp_path
    
    PhoneticLearner._instance = old_p_instance
    BrevityLearner._instance = old_b_instance


def test_phonetic_builtin_normalizations(temp_learning_env):
    p_learner, _, _ = temp_learning_env
    
    raw = "run pie test on test license dot pie"
    norm = p_learner.normalize_stt(raw)
    assert "pytest" in norm
    assert ".py" in norm

    raw_k8s = "cube cuddle get pods"
    assert p_learner.normalize_stt(raw_k8s) == "kubectl get pods"


def test_phonetic_record_and_persist(temp_learning_env):
    p_learner, _, tmp_path = temp_learning_env
    
    p_learner.record_correction("wifi pricing", "vifi pricing")
    assert p_learner.normalize_stt("check wifi pricing please") == "check vifi pricing please"

    # Verify reload from disk
    new_learner = PhoneticLearner(memory_path=tmp_path / "phonetic_memory.json")
    assert new_learner.normalize_stt("check wifi pricing please") == "check vifi pricing please"


def test_phonetic_record_symbols(temp_learning_env):
    p_learner, _, _ = temp_learning_env
    
    p_learner.record_symbol("UnifiedDynamicIslandHUD")
    raw = "open the unified dynamic island hud"
    assert "UnifiedDynamicIslandHUD" in p_learner.normalize_stt(raw)


def test_brevity_learner_barge_in_adaptation(temp_learning_env):
    _, b_learner, _ = temp_learning_env
    
    initial_limit = b_learner.get_optimal_max_words()
    assert initial_limit == 32

    # Developer interrupted turn
    b_learner.record_turn(word_count=35, was_interrupted=True)
    assert b_learner.get_optimal_max_words() == 30
    assert b_learner.total_interruptions == 1
    assert b_learner.get_interruption_rate() == 1.0

    # Another interruption dials down further
    b_learner.record_turn(word_count=30, was_interrupted=True)
    assert b_learner.get_optimal_max_words() == 28

    long_text = "This is a very long response that explains every single detail of the architecture including all classes, functions, and endpoints without stopping."
    soundbite = b_learner.format_soundbite(long_text)
    assert len(soundbite.split()) <= 28


def test_developer_normalizer_integration(temp_learning_env):
    p_learner, _, _ = temp_learning_env
    p_learner.record_correction("ant gravity", "Antigravity")
    
    res = PhoneticNormalizer.normalize("let's ask ant gravity to run pie test")
    assert "Antigravity" in res
    assert "pytest" in res
