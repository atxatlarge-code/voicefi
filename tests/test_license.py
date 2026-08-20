"""Unit tests for License and FeatureGate."""

from talk2me.config import Talk2MeConfig
from talk2me.license import FeatureGate


def test_community_tier_capabilities():
    config = Talk2MeConfig(tier="community")
    assert FeatureGate.is_pro(config) is False
    assert FeatureGate.can_use_feature("mac_say", config) is True
    assert FeatureGate.can_use_feature("edge_tts", config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is False


def test_pro_tier_capabilities():
    config = Talk2MeConfig(tier="pro", license_key="PRO-VALID-LICENSE-KEY-123")
    assert FeatureGate.is_pro(config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is True

    summary = FeatureGate.get_tier_summary(config)
    assert summary["tier"] == "Pro"
    assert summary["features"]["elevenlabs_neural"] is True
