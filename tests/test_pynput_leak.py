import sys
import time
import pytest

@pytest.mark.skipif(sys.platform != "darwin", reason="Quartz CGEventTap is macOS-only")
def test_pynput_listener_no_event_tap_leak():
    """Verify that pynput keyboard listeners cleanly invalidate CGEventTaps when stopped."""
    import Quartz
    import voicefi  # Ensure patch_pynput_darwin() runs
    from pynput import keyboard

    def count_my_taps():
        import os
        err, taps, count = Quartz.CGGetEventTapList(200, None, None)
        pid = os.getpid()
        my_taps = [t for t in taps if t.tappingProcess == pid]
        return len(my_taps), sum(1 for t in my_taps if t.enabled)

    initial_total, initial_enabled = count_my_taps()

    # Create and stop multiple listeners
    for _ in range(5):
        listener = keyboard.Listener(on_press=lambda k: None)
        listener.daemon = True
        listener.start()
        time.sleep(0.05)
        listener.stop()
        listener.join(timeout=1.0)
        time.sleep(0.05)

    final_total, final_enabled = count_my_taps()

    # Neither total taps nor enabled taps should have increased
    assert final_enabled <= initial_enabled, f"Leaked enabled taps: {final_enabled} > {initial_enabled}"
    assert final_total <= initial_total, f"Leaked total taps: {final_total} > {initial_total}"
