"""Unit tests for License and FeatureGate."""

from voicefi.config import VoiceFiConfig
from voicefi.license import FeatureGate


def test_community_tier_capabilities():
    config = VoiceFiConfig(tier="community")
    assert FeatureGate.is_pro(config) is False
    assert FeatureGate.can_use_feature("mac_say", config) is True
    assert FeatureGate.can_use_feature("edge_tts", config) is True
    assert FeatureGate.can_use_feature("whisper_local_stt", config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is False
    assert FeatureGate.can_use_feature("streaming_stt", config) is False


def test_pro_tier_capabilities():
    config = VoiceFiConfig(tier="pro", license_key="PRO-VALID-LICENSE-KEY-123")
    assert FeatureGate.is_pro(config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is True
    assert FeatureGate.can_use_feature("streaming_stt", config) is True

    summary = FeatureGate.get_tier_summary(config)
    assert summary["tier"] == "Pro"
    assert summary["features"]["elevenlabs_neural"] is True
    assert summary["features"]["streaming_stt"] is True


def test_org_tier_capabilities():
    config = VoiceFiConfig(tier="org", license_key="ORG-CORP-999")
    assert FeatureGate.is_pro(config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is True
    assert FeatureGate.can_use_feature("streaming_stt", config) is True

    summary = FeatureGate.get_tier_summary(config)
    assert summary["tier"] == "Org"
    assert summary["features"]["streaming_stt"] is True
