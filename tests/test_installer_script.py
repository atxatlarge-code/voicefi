"""
Unit tests to verify the integrity and completeness of the VoiceFi installer script.
Ensures that install.sh always contains necessary bootstrapping, autostart, and onboarding flows.
"""

from pathlib import Path
import subprocess

INSTALL_SH_PATH = Path(__file__).parent.parent / "install.sh"


def test_installer_file_exists():
    assert INSTALL_SH_PATH.exists(), "install.sh must exist in repository root"


def test_installer_syntax_valid():
    """Verify install.sh has valid bash syntax."""
    res = subprocess.run(["bash", "-n", str(INSTALL_SH_PATH)], capture_output=True, text=True)
    assert res.returncode == 0, f"install.sh syntax check failed: {res.stderr}"


def test_installer_contains_required_steps():
    """Ensure installer includes autostart and onboarding invocations."""
    content = INSTALL_SH_PATH.read_text(encoding="utf-8")
    
    assert "voicefi\" setup" in content, "Installer must run voicefi setup"
    assert "voicefi\" autostart" in content, "Installer must enable autostart daemon"
    assert "voicefi\" onboarding" in content, "Installer must trigger onboarding flow"
    assert "vifi.sh" in content, "Installer must reference vifi.sh"
