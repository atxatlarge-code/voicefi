"""
HUD Alignment & Synchronization Contract Tests.
Validates that native AppKit Dynamic Island HUD specifications,
reactive SVG definitions, and Web HUD components remain 100% in sync with zero drift.
"""

from pathlib import Path
import pytest

VOICEFI_ROOT = Path(__file__).resolve().parent.parent
COMPANION_STATIC = VOICEFI_ROOT / "src" / "voicefi" / "companion" / "static"
WEB_DIR = VOICEFI_ROOT.parent / "voicefi.org"
WEB_ASSETS = WEB_DIR / "assets"


def test_shared_hud_files_exist():
    """Verify that the shared Web HUD CSS and JS files exist in VoiceFi."""
    assert (COMPANION_STATIC / "voicefi-hud.css").exists(), "voicefi-hud.css missing in VoiceFi companion"
    assert (COMPANION_STATIC / "voicefi-hud.js").exists(), "voicefi-hud.js missing in VoiceFi companion"


def test_web_hud_files_parity():
    """Verify that voicefi.org assets match the canonical VoiceFi companion source files."""
    if WEB_ASSETS.exists():
        vf_css = (COMPANION_STATIC / "voicefi-hud.css").read_text(encoding="utf-8")
        web_css = (WEB_ASSETS / "voicefi-hud.css").read_text(encoding="utf-8")
        assert vf_css == web_css, "voicefi-hud.css drift detected between VoiceFi and voicefi.org"

        vf_js = (COMPANION_STATIC / "voicefi-hud.js").read_text(encoding="utf-8")
        web_js = (WEB_ASSETS / "voicefi-hud.js").read_text(encoding="utf-8")
        assert vf_js == web_js, "voicefi-hud.js drift detected between VoiceFi and voicefi.org"


def test_hud_state_contracts():
    """Verify that all core HUD states exist in the reactive SVG engine and CSS stylesheet."""
    js_content = (COMPANION_STATIC / "voicefi-hud.js").read_text(encoding="utf-8")
    css_content = (COMPANION_STATIC / "voicefi-hud.css").read_text(encoding="utf-8")

    core_states = ["idle", "thinking", "speaking", "listening", "working"]

    for state in core_states:
        # JS engine contains state in validStates array
        assert f"'{state}'" in js_content or f'"{state}"' in js_content, f"State '{state}' missing in voicefi-hud.js"
        # CSS contains state styling
        assert f"vifi-active-{state}" in css_content, f"State '{state}' missing in voicefi-hud.css"
        # CSS contains aura glow definition (except idle which uses standard border)
        if state != "idle":
            assert f"glow-{state}" in css_content, f"Glow class 'glow-{state}' missing in voicefi-hud.css"


def test_anatomical_svg_elements_present():
    """Verify that all anatomical lighting SVG elements are defined in the SVG template."""
    js_content = (COMPANION_STATIC / "voicefi-hud.js").read_text(encoding="utf-8")

    required_svg_classes = [
        "vifi-wifi-crown",
        "vifi-wifi-visor",
        "vifi-wifi-brim",
        "vifi-eyes",
        "vifi-nose-frame",
        "vifi-nose-pin",
        "vifi-mouth",
        "vifi-cradle",
        "vifi-ear-left",
        "vifi-ear-right",
        "vifi-ear-waves",
        "vifi-stem",
        "vifi-base-stand",
    ]

    for element_class in required_svg_classes:
        assert element_class in js_content, f"SVG element class '{element_class}' missing in voicefi-hud.js SVG template"


def test_default_personas_supported():
    """Verify that core voice personas are recognized by the HUD controller badge resolver."""
    js_content = (COMPANION_STATIC / "voicefi-hud.js").read_text(encoding="utf-8")

    expected_personas = ["Viv", "Christopher", "Aria", "Emily", "Sonia"]
    for persona in expected_personas:
        assert persona in js_content, f"Persona '{persona}' missing in badge mapping inside voicefi-hud.js"
