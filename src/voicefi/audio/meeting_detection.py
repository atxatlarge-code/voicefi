import subprocess
import re

def is_user_on_call() -> bool:
    """
    Check if the user is currently on an active meeting/call by looking at pmset assertions.
    Detects Zoom, Teams, Webex, and WebRTC (browser-based) calls.
    """
    try:
        res = subprocess.run(["pmset", "-g", "assertions"], capture_output=True, text=True)
        if res.returncode != 0:
            return False
        
        output = res.stdout
        
        # Look for video conferencing apps
        # Check for PreventUserIdleSystemSleep or NoDisplaySleepAssertion by zoom, teams, webex, etc.
        if re.search(r'(?i)(zoom\.us|Microsoft Teams|WebRTC|cameracaptured|Describe Activity Type|Webex)', output):
            return True
            
        return False
    except Exception:
        return False
