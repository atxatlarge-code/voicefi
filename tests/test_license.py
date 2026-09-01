"""Unit tests for License, 14-Day Free Trial, and FeatureGate."""

import time
from voicefi.config import VoiceFiConfig
from voicefi.license import FeatureGate


def test_community_tier_when_trial_expired():
    """Verify community tier capabilities when 14-day trial has elapsed."""
    from voicefi.license import get_hardware_identifier, compute_trial_hmac

    hw_id = get_hardware_identifier()
    # Trial started 15 days ago
    expired_start = time.time() - (15 * 86400)
    seal = compute_trial_hmac(expired_start, hw_id, 14)
    config = VoiceFiConfig(tier="community", trial_started_at=expired_start, trial_seal=seal)

    trial = FeatureGate.get_trial_status(config)
    assert trial["is_expired"] is True
    assert trial["is_active"] is False
    assert trial["days_remaining"] == 0

    assert FeatureGate.is_pro(config) is False
    assert FeatureGate.can_use_feature("mac_say", config) is True
    assert FeatureGate.can_use_feature("edge_tts", config) is True
    assert FeatureGate.can_use_feature("whisper_local_stt", config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is False
    assert FeatureGate.can_use_feature("streaming_stt", config) is False

    summary = FeatureGate.get_tier_summary(config)
    assert "Community" in summary["tier"]
    assert summary["is_pro"] is False
    assert summary["trial_expired"] is True


def test_14_day_free_trial_active_capabilities():
    """Verify 14-day free trial unlocks Pro capabilities on fresh install."""
    from voicefi.license import get_hardware_identifier, compute_trial_hmac

    hw_id = get_hardware_identifier()
    # Fresh install: trial started 2 days ago
    two_days_ago = time.time() - (2 * 86400)
    seal = compute_trial_hmac(two_days_ago, hw_id, 14)
    config = VoiceFiConfig(tier="community", trial_started_at=two_days_ago, trial_seal=seal)

    trial = FeatureGate.get_trial_status(config)
    assert trial["is_trial"] is True
    assert trial["is_active"] is True
    assert trial["is_expired"] is False
    assert trial["days_remaining"] == 12

    # All Pro features unlocked during free trial
    assert FeatureGate.is_pro(config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is True
    assert FeatureGate.can_use_feature("streaming_stt", config) is True

    summary = FeatureGate.get_tier_summary(config)
    assert summary["is_pro"] is True
    assert summary["is_trial"] is True
    assert summary["trial_days_remaining"] == 12
    assert "12d left" in summary["tier"] or "Pro Trial" in summary["tier"]
    assert summary["pricing"]["monthly_usd"] == 9.0
    assert summary["pricing"]["annual_special_usd"] == 69.0
    assert summary["pricing"]["annual_monthly_equivalent"] == 5.75


def test_pro_tier_capabilities():
    """Verify cryptographically signed Pro license unlocks features permanently."""
    from voicefi.license import generate_license_key

    valid_key = generate_license_key(tier="PRO", expires="PERP", tag="TEST_USER")
    config = VoiceFiConfig(tier="pro", license_key=valid_key)
    assert FeatureGate.is_pro(config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is True
    assert FeatureGate.can_use_feature("streaming_stt", config) is True

    summary = FeatureGate.get_tier_summary(config)
    assert summary["tier"] == "Pro"
    assert summary["is_licensed"] is True
    assert summary["is_trial"] is False
    assert summary["license_info"]["expires_at"] == "Perpetual"
    assert summary["license_info"]["tag"] == "TEST_USER"
    assert summary["features"]["elevenlabs_neural"] is True
    assert summary["features"]["streaming_stt"] is True


def test_time_limited_license_key_valid():
    """Verify time-limited license key is active before expiration date."""
    from voicefi.license import generate_license_key

    # Expires in 2035
    key = generate_license_key(tier="PRO", expires="20351231", tag="ANNUAL_PASS")
    config = VoiceFiConfig(tier="pro", license_key=key)
    assert FeatureGate.is_pro(config) is True

    summary = FeatureGate.get_tier_summary(config)
    assert summary["is_licensed"] is True
    assert summary["license_info"]["is_expired"] is False
    assert summary["license_info"]["expires_at"] == "2035-12-31"


def test_time_limited_license_key_expired():
    """Verify expired time-limited license key is rejected and locked."""
    from voicefi.license import generate_license_key, get_hardware_identifier, compute_trial_hmac

    # Expired in 2024
    key = generate_license_key(tier="PRO", expires="20240101", tag="BETA_PASS")
    # Expired trial + expired key
    hw_id = get_hardware_identifier()
    expired_start = time.time() - (20 * 86400)
    seal = compute_trial_hmac(expired_start, hw_id, 14)

    config = VoiceFiConfig(
        tier="pro", license_key=key, trial_started_at=expired_start, trial_seal=seal
    )
    assert FeatureGate.is_pro(config) is False
    assert FeatureGate.can_use_feature("elevenlabs", config) is False

    summary = FeatureGate.get_tier_summary(config)
    assert summary["is_licensed"] is False
    assert summary["license_info"]["is_expired"] is True


def test_forged_license_key_rejection():
    """Verify forged or guessed license keys are rejected."""
    from voicefi.license import verify_license_key

    # Format mismatch / random guess
    res1 = verify_license_key("PRO-COMMUNITY-1234")
    assert res1["is_valid"] is False

    # Valid prefix, forged signature
    res2 = verify_license_key("VF1-PRO-PERP-GUESS.FAKESIGNATURE1234567890")
    assert res2["is_valid"] is False

    # Valid prefix, 64-byte forged signature
    res3 = verify_license_key(
        "VF1-PRO-PERP-GUESS.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )
    assert res3["is_valid"] is False


def test_org_tier_capabilities():
    """Verify licensed Org tier with dedicated org_code overrides trial."""
    config = VoiceFiConfig(tier="org", org_code="ACME_CORP")
    assert FeatureGate.is_pro(config) is True
    assert FeatureGate.can_use_feature("elevenlabs", config) is True
    assert FeatureGate.can_use_feature("streaming_stt", config) is True

    summary = FeatureGate.get_tier_summary(config)
    assert summary["tier"] == "Org"
    assert summary["is_licensed"] is True
    assert summary["features"]["streaming_stt"] is True


def test_trial_seal_tamper_detection():
    """Verify modifying trial timestamp without valid HMAC seal expires trial."""
    from voicefi.license import get_hardware_identifier, compute_trial_hmac

    hw_id = get_hardware_identifier()
    valid_start = time.time() - (2 * 86400)
    valid_seal = compute_trial_hmac(valid_start, hw_id, 14)

    # Valid config with seal
    config = VoiceFiConfig(trial_started_at=valid_start, trial_seal=valid_seal)
    status = FeatureGate.get_trial_status(config)
    assert status["is_active"] is True
    assert status["tampered"] is False

    # Tampered config: user rolled back start date in YAML without valid seal
    tampered_config = VoiceFiConfig(trial_started_at=time.time(), trial_seal="invalid-fake-seal")
    status_tampered = FeatureGate.get_trial_status(tampered_config)
    assert status_tampered["tampered"] is True
    assert status_tampered["is_active"] is False
    assert status_tampered["is_expired"] is True


def test_clock_rollback_detection():
    """Verify setting system clock backwards is detected."""
    from voicefi.license import get_hardware_identifier, compute_trial_hmac

    hw_id = get_hardware_identifier()
    future_start = time.time() + (10 * 86400)  # Future date
    seal = compute_trial_hmac(future_start, hw_id, 14)

    config = VoiceFiConfig(trial_started_at=future_start, trial_seal=seal)
    status = FeatureGate.get_trial_status(config)
    assert status["tampered"] is True
    assert status["is_active"] is False

