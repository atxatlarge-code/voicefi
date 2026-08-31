"""
Native macOS User Notification dispatcher with robust AppleScript fallback.
Handles notifications cleanly without requiring a signed Info.plist bundle.
"""

import subprocess


def show_notification(title: str, subtitle: str = "", message: str = "") -> bool:
    """Display native macOS Notification Center banner."""
    # 1. Try rumps notification
    try:
        import rumps

        rumps.notification(title, subtitle, message)
        return True
    except Exception:
        pass

    # 2. Resilient osascript notification fallback
    try:
        clean_title = title.replace('"', '\\"')
        clean_sub = subtitle.replace('"', '\\"')
        clean_msg = message.replace('"', '\\"')

        parts = [f'display notification "{clean_msg}"']
        if clean_title:
            parts.append(f'with title "{clean_title}"')
        if clean_sub:
            parts.append(f'subtitle "{clean_sub}"')

        script = " ".join(parts)
        res = subprocess.run(
            ["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return res.returncode == 0
    except Exception:
        return False
