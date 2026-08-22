"""
License and Tier Management for Voicegency.
Handles feature gates between Community (Open-Source) and Pro tiers.
"""

from typing import Dict, Any, Optional
from voicegency.config import VoicegencyConfig


class FeatureGate:
    """Controls availability of features based on active tier and license key."""

    PRO_PROVIDERS = {"elevenlabs", "openai_realtime", "cartesia"}

    @classmethod
    def is_pro(cls, config: VoicegencyConfig) -> bool:
        """Check if user has Pro tier enabled with a valid license format."""
        if config.tier == "pro" and config.license_key and len(config.license_key.strip()) >= 8:
            return True
        return False

    @classmethod
    def can_use_feature(cls, feature_name: str, config: VoicegencyConfig) -> bool:
        """Verify if a specific feature is enabled for the active tier."""
        if feature_name in cls.PRO_PROVIDERS:
            return cls.is_pro(config)
        return True

    @classmethod
    def get_tier_summary(cls, config: VoicegencyConfig) -> Dict[str, Any]:
        """Return human-readable tier status and capabilities."""
        pro_active = cls.is_pro(config)
        return {
            "tier": "Pro" if pro_active else "Community",
            "license_valid": pro_active,
            "features": {
                "mac_say_tts": True,
                "edge_tts": True,
                "whisper_local_stt": True,
                "groq_stt": True,
                "antigravity_hooks": True,
                "global_hotkey": True,
                "elevenlabs_neural": pro_active,
                "custom_wake_words": pro_active,
                "multi_agent_dashboard": pro_active,
            },
        }
