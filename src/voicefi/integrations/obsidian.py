"""
Obsidian integration, app installer, and automated plugin installer for VoiceFi.
Discovers local Obsidian vaults, installs the VoiceFi plugin bundle,
and enables it automatically in community-plugins.json.
"""

import json
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import List, Dict, Optional, Any


def get_obsidian_config_path() -> Path:
    """Path to Obsidian's global application configuration."""
    return Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"


def is_obsidian_installed() -> bool:
    """Check if the Obsidian desktop application is installed on macOS."""
    candidates = [
        Path("/Applications/Obsidian.app"),
        Path.home() / "Applications" / "Obsidian.app",
    ]
    return any(c.is_dir() for c in candidates)


def install_obsidian_app() -> bool:
    """
    Attempt to install Obsidian on macOS via Homebrew cask,
    or fallback to opening the official download page in the browser.
    """
    brew_path = shutil.which("brew")
    if brew_path:
        print("🍺 Homebrew detected. Installing Obsidian via 'brew install --cask obsidian'...")
        try:
            res = subprocess.run(
                [brew_path, "install", "--cask", "obsidian"],
                check=False,
            )
            if res.returncode == 0 and is_obsidian_installed():
                print("✅ Obsidian successfully installed via Homebrew!")
                return True
        except Exception as e:
            print(f"⚠️ Homebrew installation error: {e}")

    print("🌐 Opening official Obsidian download page in your browser...")
    webbrowser.open("https://obsidian.md/download")
    return False


def find_obsidian_vaults() -> List[Dict[str, Any]]:
    """
    Discover all registered Obsidian vaults on the local machine.
    Returns list of dicts with vault info: {'id': str, 'path': Path, 'name': str, 'open': bool, 'ts': int}.
    """
    vaults: List[Dict[str, Any]] = []
    config_file = get_obsidian_config_path()

    if config_file.is_file():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_vaults = data.get("vaults", {})
            for vid, vinfo in raw_vaults.items():
                vpath_str = vinfo.get("path")
                if vpath_str:
                    vp = Path(vpath_str)
                    if vp.is_dir():
                        vaults.append({
                            "id": vid,
                            "path": vp,
                            "name": vp.name,
                            "open": bool(vinfo.get("open", False)),
                            "ts": vinfo.get("ts", 0),
                        })
        except Exception:
            pass

    # Sort open vaults first, then by most recent timestamp
    vaults.sort(key=lambda v: (v["open"], v["ts"]), reverse=True)
    return vaults


def create_starter_vault(vault_path: Optional[Path] = None) -> Path:
    """
    Create a new starter Obsidian vault with starter folders, VoiceFi plugin,
    and a welcome note.
    """
    target = vault_path or (Path.home() / "Documents" / "Obsidian Vault")
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    # Create Welcome Note
    welcome_note = target / "🎙️ VoiceFi Second Voice.md"
    if not welcome_note.is_file():
        welcome_content = """# 🎙️ Welcome to VoiceFi: Second Brain, Second Voice

> "The vocal cords for your vault."

VoiceFi connects your Obsidian knowledge base directly to your local voice and AI coding agents.

## 🚀 Quick Voice Actions:
- **Toggle Active Listening:** Click the 🎙️ microphone icon in the left ribbon (or press `Cmd + P` ➔ *Toggle Active Listening Session*).
- **Read Note Aloud:** Press `Cmd + P` ➔ *Speak Current Note (TTS)*.
- **Hands-Free Chat:** Talk naturally to your agents hands-free without copy-pasting code into the terminal.

---
*Powered by OpenAI Whisper (Local STT) & Microsoft Neural Speech (TTS)*
"""
        welcome_note.write_text(welcome_content, encoding="utf-8")

    return target


def get_plugin_assets_dir() -> Optional[Path]:
    """Find the directory containing the compiled obsidian-plugin assets."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "obsidian-plugin",
        Path.cwd() / "obsidian-plugin",
        Path.home() / "Projects" / "VoiceFi" / "obsidian-plugin",
    ]
    for c in candidates:
        if (c / "manifest.json").is_file() and (c / "main.js").is_file():
            return c
    return None


def install_plugin_to_vault(vault_path: Path, assets_dir: Optional[Path] = None) -> bool:
    """
    Install and automatically enable the VoiceFi plugin in an Obsidian vault.
    """
    vault = Path(vault_path).expanduser().resolve()
    if not vault.is_dir():
        vault.mkdir(parents=True, exist_ok=True)

    obsidian_dir = vault / ".obsidian"
    obsidian_dir.mkdir(parents=True, exist_ok=True)

    plugins_dir = obsidian_dir / "plugins" / "voicefi"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    source_dir = assets_dir or get_plugin_assets_dir()
    if not source_dir:
        raise FileNotFoundError(
            "Could not locate compiled obsidian-plugin assets (manifest.json, main.js). "
            "Please run 'npm run build' inside the obsidian-plugin directory."
        )

    # Copy plugin bundle files
    shutil.copy2(source_dir / "manifest.json", plugins_dir / "manifest.json")
    shutil.copy2(source_dir / "main.js", plugins_dir / "main.js")
    if (source_dir / "styles.css").is_file():
        shutil.copy2(source_dir / "styles.css", plugins_dir / "styles.css")

    # Automatically enable in community-plugins.json
    community_json = obsidian_dir / "community-plugins.json"
    enabled_plugins = []
    if community_json.is_file():
        try:
            with open(community_json, "r", encoding="utf-8") as f:
                enabled_plugins = json.load(f)
            if not isinstance(enabled_plugins, list):
                enabled_plugins = []
        except Exception:
            enabled_plugins = []

    plugin_id = "voicefi-obsidian"
    try:
        with open(plugins_dir / "manifest.json", "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
            plugin_id = manifest_data.get("id", plugin_id)
    except Exception:
        pass

    if plugin_id not in enabled_plugins:
        enabled_plugins.append(plugin_id)
        with open(community_json, "w", encoding="utf-8") as f:
            json.dump(enabled_plugins, f, indent=2)

    return True
