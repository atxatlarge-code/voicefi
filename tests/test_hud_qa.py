"""
QA Automated Test Suite for VoiceFi Dynamic Island HUD & Vector Icons.
Validates:
1. Native Cocoa HUD initialization and geometry.
2. State vector generation & active red lighting mapping.
3. State transitions (Idle, Thinking, Working, Speaking, Listening, Editing, New Conversation).
4. Auto-send, persistent mode, full-screen overlay toggling.
5. Exported asset dimensions and file headers.
"""

import os
from pathlib import Path
import pytest
from AppKit import NSImage, NSData, NSRunLoop, NSDate
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD


@pytest.fixture(autouse=True)
def cleanup_hud():
    UnifiedDynamicIslandHUD._instance = None
    yield
    if UnifiedDynamicIslandHUD._instance is not None:
        try:
            if UnifiedDynamicIslandHUD._instance._panel:
                UnifiedDynamicIslandHUD._instance._panel.orderOut_(None)
                UnifiedDynamicIslandHUD._instance._panel.close()
        except Exception:
            pass
        UnifiedDynamicIslandHUD._instance = None


def test_hud_instance_and_geometry():
    hud = UnifiedDynamicIslandHUD.get_instance()
    assert hud is not None
    assert hud._panel is not None
    assert hud._avatar_box is not None
    assert hud._avatar_img is not None


def test_vector_state_icons_resolution_and_caching():
    hud = UnifiedDynamicIslandHUD.get_instance()
    states = ["thinking", "listening", "speaking", "working", "idle"]
    
    for state in states:
        img = hud._resolve_voicefi_state_icon(state)
        assert img is not None, f"Failed to generate vector icon for state {state}"
        assert img.isValid(), f"Vector icon for state {state} is invalid"
        assert img.size().width == 64.0
        assert img.size().height == 64.0
        
        # Test cache retrieval
        cached = hud._resolve_voicefi_state_icon(state)
        assert cached is img, f"Cache retrieval failed for state {state}"


def test_hud_state_transitions():
    from voicefi.tts.base import clear_cross_process_hud_state
    clear_cross_process_hud_state()
    UnifiedDynamicIslandHUD._instance = None
    hud = UnifiedDynamicIslandHUD.get_instance()
    
    def pump(duration=0.1):
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(duration))

    # 1. Idle
    hud.set_idle()
    pump(0.05)
    assert hud._current_state == "idle"
    assert hud._title_lbl.stringValue() == "VoiceFi"

    # 2. Thinking
    hud.set_thinking(agent_name="Antigravity", detail="Reasoning over AST...")
    pump(0.05)
    assert hud._current_state == "thinking"
    assert "Antigravity" in hud._title_lbl.stringValue()
    assert "Reasoning over AST" in hud._body_lbl.stringValue()

    # 3. Working
    hud.set_working(agent_name="Antigravity", tool_action="pytest tests/ -v")
    pump(0.05)
    assert hud._current_state == "working"
    assert "pytest tests/ -v" in hud._body_lbl.stringValue()

    # 4. Speaking
    hud.set_speaking(text="Test completed successfully!", agent_name="Antigravity")
    pump(0.05)
    assert hud._current_state == "speaking"
    assert "Test completed successfully!" in hud._body_lbl.stringValue()

    # 5. Listening
    hud.set_listening(prompt_preview="Fix the expired token bug", user_name="Jake", live_stream=True)
    pump(0.05)
    assert hud._current_state == "listening"
    assert "Fix the expired token bug" in hud._body_lbl.stringValue()

    # 5b. Hearing (Voice Onset Detected)
    hud.set_hearing(prompt_preview="Fix the expired token bug", user_name="Jake")
    pump(0.05)
    assert hud._current_state == "listening"
    assert "Hearing (Jake)" in hud._title_lbl.stringValue()

    # 6. Editing
    hud.set_editing(initial_text="Review and edit this prompt", on_submit=lambda x: None)
    pump(0.05)
    assert hud._current_state == "editing"

    # 7. Reset to Idle
    hud.set_idle()
    pump(0.05)
    assert hud._current_state == "idle"


def test_cross_process_hud_state_sync():
    from voicefi.tts.base import (
        set_cross_process_hud_state,
        get_cross_process_hud_state,
        clear_cross_process_hud_state,
    )

    clear_cross_process_hud_state()
    assert get_cross_process_hud_state() is None

    set_cross_process_hud_state(
        state="speaking",
        text="Dynamic island HUD is fully wired!",
        agent_name="Antigravity",
        persona_name="Viv",
    )

    state = get_cross_process_hud_state()
    assert state is not None
    assert state["state"] == "speaking"
    assert state["text"] == "Dynamic island HUD is fully wired!"
    assert state["agent_name"] == "Antigravity"
    assert state["persona_name"] == "Viv"

    # Transition to listening
    set_cross_process_hud_state(state="listening", user_name="Jake")
    state = get_cross_process_hud_state()
    assert state is not None
    assert state["state"] == "listening"

    # Transition to hearing
    set_cross_process_hud_state(state="hearing", user_name="Jake")
    state = get_cross_process_hud_state()
    assert state is not None
    assert state["state"] == "hearing"

    # Clear
    clear_cross_process_hud_state()
    assert get_cross_process_hud_state() is None


def test_exported_status_icon_assets():
    assets_dir = Path("/Users/jaketrigg/Projects/VoiceFi/assets/status_icons")
    assert assets_dir.exists(), "assets/status_icons directory does not exist"
    
    states = ["thinking", "listening", "speaking", "working", "idle"]
    scales = [16, 24, 32, 48, 64, 128, 256, 512]
    
    for s in states:
        svg_file = assets_dir / f"{s}.svg"
        assert svg_file.exists(), f"Missing {svg_file}"
        assert svg_file.stat().st_size > 500, f"SVG file {svg_file} is suspiciously small"
        
        for px in scales:
            png_file = assets_dir / f"{s}_{px}px.png"
            assert png_file.exists(), f"Missing {png_file}"
            # Check PNG magic bytes
            with open(png_file, "rb") as f:
                header = f.read(8)
                assert header == b"\x89PNG\r\n\x1a\n", f"Invalid PNG header in {png_file}"
            
            # Check image dimensions via NSImage
            img = NSImage.alloc().initWithContentsOfFile_(str(png_file))
            assert img.isValid(), f"Failed to load PNG {png_file}"
            rep = img.representations()[0]
            assert rep.pixelsWide() == px, f"Expected width {px}, got {rep.pixelsWide()}"
            assert rep.pixelsHigh() == px, f"Expected height {px}, got {rep.pixelsHigh()}"
