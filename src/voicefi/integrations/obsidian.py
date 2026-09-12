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
                        vaults.append(
                            {
                                "id": vid,
                                "path": vp,
                                "name": vp.name,
                                "open": bool(vinfo.get("open", False)),
                                "ts": vinfo.get("ts", 0),
                            }
                        )
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


def is_plugin_installed(vault_path: Path) -> bool:
    """Check if the VoiceFi plugin is installed in the given vault."""
    vp = Path(vault_path).expanduser().resolve()
    plugin_dir = vp / ".obsidian" / "plugins" / "voicefi"
    return (plugin_dir / "manifest.json").is_file() and (plugin_dir / "main.js").is_file()


import datetime
import re
import time


def get_primary_vault(config: Optional[Any] = None) -> Optional[Path]:
    """Resolve the active or default Obsidian vault path."""
    if config and hasattr(config, "obsidian") and config.obsidian.vault_path:
        vp = Path(config.obsidian.vault_path).expanduser().resolve()
        if vp.is_dir():
            return vp
    vaults = find_obsidian_vaults()
    if vaults:
        # First entry is open=True or most recent
        return vaults[0]["path"]
    default_doc = Path.home() / "Documents" / "Obsidian Vault"
    if default_doc.is_dir():
        return default_doc
    return None


def get_daily_note_path(
    vault_path: Path,
    today: Optional[datetime.date] = None,
    config: Optional[Any] = None,
) -> Path:
    """Resolve the path to the daily note in the given vault."""
    date_target = today or datetime.date.today()
    date_iso = date_target.strftime("%Y-%m-%d")

    custom_folder = None
    if config and hasattr(config, "obsidian"):
        if config.obsidian.daily_note_folder:
            custom_folder = config.obsidian.daily_note_folder
        if config.obsidian.daily_note_format:
            try:
                date_iso = date_target.strftime(config.obsidian.daily_note_format)
            except Exception:
                date_iso = date_target.strftime("%Y-%m-%d")

    if not custom_folder:
        daily_json = vault_path / ".obsidian" / "daily-notes.json"
        if daily_json.is_file():
            try:
                with open(daily_json, "r", encoding="utf-8") as f:
                    d_cfg = json.load(f)
                if d_cfg.get("folder"):
                    custom_folder = d_cfg.get("folder")
                if d_cfg.get("format"):
                    fmt = d_cfg.get("format")
                    fmt = fmt.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
                    try:
                        date_iso = date_target.strftime(fmt)
                    except Exception:
                        date_iso = date_target.strftime("%Y-%m-%d")
            except Exception:
                pass

    note_name = f"{date_iso}.md" if not date_iso.endswith(".md") else date_iso
    if custom_folder:
        folder_path = vault_path / custom_folder
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path / note_name

    daily_notes_dir = vault_path / "Daily Notes"
    if daily_notes_dir.is_dir():
        return daily_notes_dir / note_name

    return vault_path / note_name


def append_quick_capture_to_vault(
    text: str,
    vault_path: Optional[Path] = None,
    timestamp: Optional[float] = None,
    config: Optional[Any] = None,
) -> Dict[str, Any]:
    """Append a quick voice capture note directly into today's daily note."""
    clean_text = text.strip()
    if not clean_text:
        return {"status": "error", "error": "Empty text"}

    vault = vault_path or get_primary_vault(config)
    if not vault or not vault.is_dir():
        return {"status": "error", "error": "No Obsidian vault found"}

    now = datetime.datetime.fromtimestamp(timestamp) if timestamp else datetime.datetime.now()
    daily_note = get_daily_note_path(vault, today=now.date(), config=config)

    time_str = now.strftime("%-I:%M %p")

    entry = f"\n### 🎙️ {time_str}\n- {clean_text}\n"

    if not daily_note.is_file():
        title_date = now.strftime("%Y-%m-%d")
        daily_note.write_text(f"# {title_date}\n{entry}", encoding="utf-8")
    else:
        with open(daily_note, "a", encoding="utf-8") as f:
            f.write(entry)

    return {
        "status": "ok",
        "vault_name": vault.name,
        "vault_path": str(vault),
        "daily_note_path": str(daily_note),
        "daily_note_name": daily_note.name,
        "entry": entry.strip(),
        "time": time_str,
    }


def save_memo_to_vault(
    memo_markdown: str,
    title: str,
    vault_path: Optional[Path] = None,
    config: Optional[Any] = None,
    today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Save a synthesized voice memo to <vault>/Voice Memos/<Date> - <Title>.md and backlink in daily note."""
    vault = vault_path or get_primary_vault(config)
    if not vault or not vault.is_dir():
        return {"status": "error", "error": "No Obsidian vault found"}

    date_target = today or datetime.date.today()
    date_str = date_target.strftime("%Y-%m-%d")
    clean_title = re.sub(r"[^a-zA-Z0-9_\-\s]", "", title).strip() or "Voice Memo"
    filename = f"{date_str} - {clean_title}.md"

    folder_name = "Voice Memos"
    if config and hasattr(config, "obsidian") and config.obsidian.voice_memos_folder:
        folder_name = config.obsidian.voice_memos_folder

    memos_dir = vault / folder_name
    memos_dir.mkdir(parents=True, exist_ok=True)
    memo_file = memos_dir / filename

    memo_file.write_text(memo_markdown.strip() + "\n", encoding="utf-8")

    daily_note = get_daily_note_path(vault, today=date_target, config=config)
    now = datetime.datetime.now()
    time_str = now.strftime("%-I:%M %p")
    note_stem = memo_file.stem
    backlink_entry = f"\n### 🎙️ {time_str} - Voice Memo\n- [[{note_stem}]]: {clean_title}\n"

    if not daily_note.is_file():
        daily_note.write_text(f"# {date_str}\n{backlink_entry}", encoding="utf-8")
    else:
        with open(daily_note, "a", encoding="utf-8") as f:
            f.write(backlink_entry)

    return {
        "status": "ok",
        "vault_name": vault.name,
        "vault_path": str(vault),
        "memo_path": str(memo_file),
        "memo_name": memo_file.name,
        "daily_note_path": str(daily_note),
        "backlink": f"[[{note_stem}]]",
    }


def get_today_note_content(
    vault_path: Optional[Path] = None, config: Optional[Any] = None
) -> Dict[str, Any]:
    """Retrieve the content of today's daily note for mobile companion display."""
    vault = vault_path or get_primary_vault(config)
    if not vault or not vault.is_dir():
        return {"status": "error", "error": "No Obsidian vault found", "content": ""}

    daily_note = get_daily_note_path(vault, config=config)
    if not daily_note.is_file():
        return {
            "status": "ok",
            "exists": False,
            "vault_name": vault.name,
            "vault_path": str(vault),
            "file_name": daily_note.name,
            "content": f"# {datetime.date.today().strftime('%Y-%m-%d')}\n\n*No entries yet today.*",
        }

    content = daily_note.read_text(encoding="utf-8")
    return {
        "status": "ok",
        "exists": True,
        "vault_name": vault.name,
        "vault_path": str(vault),
        "file_name": daily_note.name,
        "content": content,
        "mtime": daily_note.stat().st_mtime,
    }


def launch_agent_in_vault(
    engine: str = "antigravity",
    vault_path: Optional[Path] = None,
    config: Optional[Any] = None,
) -> Dict[str, Any]:
    """Launch or pair an AI agent (Antigravity or Claude Code) rooted in the Obsidian vault."""
    vault = vault_path or get_primary_vault(config)
    if not vault or not vault.is_dir():
        return {"status": "error", "error": "No Obsidian vault found"}

    engine_norm = engine.lower().strip()
    if engine_norm in ("claude", "claude_code"):
        cmd = f'tell application "Terminal" to do script "cd \\"{vault}\\" && claude"'
        subprocess.run(["osascript", "-e", cmd], check=False)
        return {
            "status": "ok",
            "engine": "claude",
            "vault_path": str(vault),
            "message": f"Launched Claude Code in {vault.name}",
        }
    else:
        from voicefi.integrations.injector import create_new_antigravity_conversation

        try:
            conv_id = create_new_antigravity_conversation(
                prompt=f"Connected to Obsidian Vault: {vault.name}. Workspace path: {vault}",
                title=f"Obsidian • {vault.name}",
            )
            return {
                "status": "ok",
                "engine": "antigravity",
                "vault_path": str(vault),
                "conv_id": conv_id,
                "message": f"Created Antigravity conversation for {vault.name}",
            }
        except Exception as e:
            return {
                "status": "ok",
                "engine": "antigravity",
                "vault_path": str(vault),
                "message": f"Vault path: {vault} ({e})",
            }
