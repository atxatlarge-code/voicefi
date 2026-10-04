"""
Playwright Mobile End-to-End QA Test for VoiceFi Meeting Cockpit & Highlighting Engine.
Emulates Google Pixel 7 (Android Chrome) on port 5142.
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = Path(
    "/Users/jaketrigg/.gemini/antigravity/brain/e3609773-1776-4f32-bf11-80e451353c9d"
)


def run_qa():
    print("🚀 Starting Playwright Mobile Browser QA for VoiceFi Meeting Cockpit...")
    results = {}

    with sync_playwright() as p:
        # Emulate Google Pixel 7
        device = p.devices["Pixel 7"]
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(**device, permissions=["microphone"])
        page = context.new_page()

        # Listen to console logs
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        # 1. Navigate to 1-Tap Meeting Shortcut URL
        url = "http://127.0.0.1:5142/companion?action=record"
        print(f"📱 Navigating to {url}...")
        page.goto(url, wait_until="networkidle")
        time.sleep(1.0)

        # 2. Check if Meeting Cockpit Modal opened
        cockpit = page.locator("#meetingCockpitModal")
        is_visible = cockpit.is_visible()
        results["cockpit_opened_on_action_record"] = is_visible
        print(f"✅ Cockpit visible on action=record: {is_visible}")

        # 3. Verify Header Elements
        title_val = page.locator("#meetingTitleInput").input_value()
        timer_text = page.locator("#meetingTimerText").inner_text()
        vault_badge = page.locator("#meetingVaultBadge").inner_text()
        print(f"  Title: '{title_val}', Timer: '{timer_text}', Vault: '{vault_badge}'")
        results["header_elements_present"] = bool(title_val and timer_text and vault_badge)

        # 4. Simulate room speech streaming into meeting
        print("🎙️ Simulating room discussion stream...")
        page.evaluate("""() => {
            meetingAccumulatedTranscript = "Today we reviewed the Apple Silicon Metal transcription engine. It achieves 213ms latency with only 15% CPU load. We reached consensus to deprecate the older CPU fallback.";
            renderMeetingTranscriptUI("");
        }""")
        time.sleep(0.5)

        stream_text = page.locator("#meetingTranscriptStream").inner_text()
        results["transcript_rendered"] = "Apple Silicon Metal" in stream_text
        print(f"✅ Live transcript rendered: {'Apple Silicon Metal' in stream_text}")

        # 5. Test 1-Tap "⭐ HIGHLIGHT KEY MOMENT" Button
        print("⭐ Tapping 'HIGHLIGHT KEY MOMENT' button...")
        highlight_btn = page.locator("#meetingHighlightBtn")
        highlight_btn.click()
        time.sleep(0.5)

        highlight_count = page.locator("#meetingHighlightCount").inner_text()
        key_points_text = page.locator("#meetingKeyPointsList").inner_text()
        results["highlight_count_updated"] = highlight_count == "1"
        results["key_points_pinned"] = "deprecate the older CPU fallback" in key_points_text
        print(f"✅ Highlight count: {highlight_count}, Pinned: {results['key_points_pinned']}")

        # 6. Test Tag Switcher & Add second highlight
        print("🏷️ Selecting 'Blocker' tag & adding second highlight...")
        page.locator("button:has-text('🚨 Blocker')").click()
        time.sleep(0.2)

        page.evaluate("""() => {
            meetingAccumulatedTranscript += " However port 5141 collision is a major blocker when the menu bar tray is active.";
            renderMeetingTranscriptUI("");
            addMeetingHighlight("Port 5141 collision is a blocker when tray is active.", "Blocker");
        }""")
        time.sleep(0.5)

        highlight_count_2 = page.locator("#meetingHighlightCount").inner_text()
        key_points_2 = page.locator("#meetingKeyPointsList").inner_text()
        results["blocker_highlight_added"] = highlight_count_2 == "2" and "Blocker" in key_points_2
        print(f"✅ Second highlight added: {results['blocker_highlight_added']}")

        # 7. Test Spoken Keyword Intercept
        print("⚡ Simulating spoken alert word: 'Viv, action item: write benchmark report'...")
        page.evaluate("""() => {
            checkMeetingSpokenTriggers("Viv, action item: write benchmark report.");
        }""")
        time.sleep(0.5)

        stream_after_cmd = page.locator("#meetingTranscriptStream").inner_text()
        results["spoken_command_intercepted"] = "Intercepted for Agent" in stream_after_cmd
        print(f"✅ Spoken alert word intercepted: {results['spoken_command_intercepted']}")

        # Capture Active Meeting Screenshot
        active_shot_path = SCREENSHOTS_DIR / "qa_meeting_cockpit_active.png"
        page.screenshot(path=str(active_shot_path))
        results["active_screenshot"] = str(active_shot_path)
        print(f"📸 Captured Active Cockpit Screenshot: {active_shot_path}")

        # 8. Test Pause / Resume Toggle
        pause_btn = page.locator("#meetingPauseBtn")
        pause_btn.click()
        time.sleep(0.3)
        pause_text = page.locator("#meetingPauseText").inner_text()
        results["pause_toggled"] = pause_text == "Resume"

        pause_btn.click()
        time.sleep(0.3)
        resume_text = page.locator("#meetingPauseText").inner_text()
        results["resume_toggled"] = resume_text == "Pause"
        print(f"✅ Pause/Resume working: {results['pause_toggled']} -> {results['resume_toggled']}")

        # 9. Test "⏹️ End & Synthesize Meeting"
        print("⏹️ Ending meeting and synthesizing to Obsidian...")
        end_btn = page.locator("#meetingEndBtn")
        end_btn.click()

        try:
            page.wait_for_selector("button:has-text('Saved to Obsidian')", timeout=15000)
            print("🎉 Synthesis completed and UI transitioned to Saved state!")
        except Exception as e:
            print("⚠️ Timeout waiting for Saved state button:", e)

        # Capture Final Screenshot after synthesis
        final_shot_path = SCREENSHOTS_DIR / "qa_meeting_cockpit_final.png"
        page.screenshot(path=str(final_shot_path))
        results["final_screenshot"] = str(final_shot_path)

        # Verify Obsidian Note was created on disk
        meetings_dir = Path("/Users/jaketrigg/Documents/Obsidian Vault/Meetings")
        today_notes = list(meetings_dir.glob("2026-09-30*.md"))
        results["obsidian_note_created"] = len(today_notes) > 0
        if today_notes:
            latest_note = sorted(today_notes, key=lambda p: p.stat().st_mtime)[-1]
            content = latest_note.read_text(encoding="utf-8")
            results["note_has_highlights"] = "Key Highlights & Bookmarks" in content
            results["note_has_blocker"] = "Blocker" in content
            results["note_has_action_items"] = "Action Items" in content or "Dispatched" in content
            print(f"📄 Obsidian note verified: {latest_note.name}")
            print(f"  Highlights in note: {results['note_has_highlights']}")
            print(f"  Blocker in note: {results['note_has_blocker']}")
            print(f"  Action items in note: {results['note_has_action_items']}")
            # Clean up test note
            latest_note.unlink(missing_ok=True)

        browser.close()

    print("\n================== QA SUMMARY ==================")
    all_passed = True
    for k, v in results.items():
        status = "✅ PASS" if v else "❌ FAIL"
        if not v:
            all_passed = False
        print(f"  {k:35}: {status} ({v})")
    print("================================================")
    return all_passed


if __name__ == "__main__":
    success = run_qa()
    exit(0 if success else 1)
