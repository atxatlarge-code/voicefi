"""
Voice Control Panel and Voice Command Engine for Voicegency.
Provides an interactive, voice-controlled web dashboard to discover, audition, tune,
and assign voices for Antigravity, subagents, and global TTS.
"""

import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from voicegency.config import (
    VoicegencyConfig,
    AgentVoiceProfile,
    load_config,
    save_config,
    get_default_config_path,
)
from voicegency.tts import (
    get_tts_engine,
    stop_all_speech,
    find_persona,
    get_curated_personas,
    list_all_available_voices,
    CURATED_PERSONAS,
)


def parse_voice_command(
    command_text: str, config: VoicegencyConfig
) -> Dict[str, Any]:
    """
    Parse natural language voice commands to control voice auditioning, selection,
    speed adjustment, filters, and playback.

    Examples:
      - "Audition Christopher" / "Test Aria" / "Let me hear Sonia"
      - "Set voice to Christopher" / "Switch my voice to Aria" / "Make Antigravity Christopher"
      - "Assign Sonia to researcher" / "Make debugger Aria"
      - "Speed up" / "Faster" / "Slower" / "Reset speed"
      - "Audition all" / "Showcase"
      - "Stop" / "Silence" / "Be quiet"
    """
    text = command_text.strip().lower()
    if not text:
        return {"action": "none", "message": "No command heard"}

    # 1. Stop / Silence commands
    if re.search(r"\b(stop|silence|be quiet|shut up|cancel|pause)\b", text):
        stop_all_speech()
        return {
            "action": "stop",
            "message": "Speech stopped",
            "speech_feedback": "Stopped.",
        }

    # 2. Showcase / Audition All
    if re.search(r"\b(showcase|audition all|test all|hear all|team showcase)\b", text):
        return {
            "action": "showcase",
            "message": "Starting multi-agent team audition showcase",
            "speech_feedback": "Starting the multi-agent voice showcase.",
        }

    # 3. Rate / Speed adjustments
    # Check explicit speed percentage or WPM (e.g. "75% speed", "75 percent", "speed to 75%", "rate 150", "make the voice 75% speed")
    pct_match = re.search(r"\b(\d+)\s*(?:%|percent)\s*(?:speed)?\b", text)
    if not pct_match:
        pct_match = re.search(r"\b(?:speed|rate)\s*(?:to|at|is|set to)?\s*(\d+)\s*(?:%|percent)?\b", text)
    if pct_match:
        val = int(pct_match.group(1))
        if val <= 120:
            target_wpm = max(int(round(200 * (val / 100.0))), 80)
            pct_desc = f"{val}%"
        else:
            target_wpm = max(min(val, 350), 80)
            pct_desc = f"{int(round((target_wpm / 200.0) * 100))}%"

        config.tts.rate = target_wpm
        if "antigravity" in config.agents:
            config.agents["antigravity"].rate = target_wpm
        save_config(config)
        return {
            "action": "rate",
            "rate": target_wpm,
            "message": f"Speech rate set to {pct_desc} ({target_wpm} WPM)",
            "speech_feedback": f"Speech speed set to {pct_desc}.",
        }

    if re.search(r"\b(faster|speed up|increase speed|talk faster)\b", text):
        new_rate = min(config.tts.rate + 25, 350)
        config.tts.rate = new_rate
        if "antigravity" in config.agents:
            config.agents["antigravity"].rate = new_rate
        save_config(config)
        return {
            "action": "rate",
            "rate": new_rate,
            "message": f"Speech rate increased to {new_rate} WPM",
            "speech_feedback": f"Speaking faster at {new_rate} words per minute.",
        }

    if re.search(r"\b(slower|slow down|decrease speed|talk slower)\b", text):
        new_rate = max(config.tts.rate - 25, 100)
        config.tts.rate = new_rate
        if "antigravity" in config.agents:
            config.agents["antigravity"].rate = new_rate
        save_config(config)
        return {
            "action": "rate",
            "rate": new_rate,
            "message": f"Speech rate decreased to {new_rate} WPM",
            "speech_feedback": f"Speaking slower at {new_rate} words per minute.",
        }

    if re.search(r"\b(normal speed|reset speed|default speed|regular speed)\b", text):
        config.tts.rate = 200
        if "antigravity" in config.agents:
            config.agents["antigravity"].rate = 200
        save_config(config)
        return {
            "action": "rate",
            "rate": 200,
            "message": "Speech rate reset to normal (200 WPM)",
            "speech_feedback": "Speech speed reset to normal.",
        }

    # 4. Helper to find persona name in spoken utterance
    known_personas = {p.name.lower(): p for p in CURATED_PERSONAS}
    extra_names = {
        "alex": "Alex",
        "samantha": "Samantha",
        "victoria": "Victoria",
        "daniel": "Daniel",
        "fred": "Fred",
        "jenny": "Jenny",
        "william": "William",
        "guy": "Guy",
        "sonia": "Sonia",
        "aria": "Aria",
        "christopher": "Christopher",
    }

    target_persona_name = None
    target_persona_obj = None

    for name in known_personas:
        if re.search(rf"\b{re.escape(name)}\b", text):
            target_persona_name = known_personas[name].name
            target_persona_obj = known_personas[name]
            break

    if not target_persona_name:
        for ename, displayName in extra_names.items():
            if re.search(rf"\b{re.escape(ename)}\b", text):
                target_persona_name = displayName
                target_persona_obj = find_persona(displayName)
                break

    # 5. Detect target agent (antigravity, researcher, debugger, architect, default)
    target_agent = "antigravity"
    if re.search(r"\b(researcher|research)\b", text):
        target_agent = "researcher"
    elif re.search(r"\b(debugger|debug|qa|tester)\b", text):
        target_agent = "debugger"
    elif re.search(r"\b(architect|devops|design)\b", text):
        target_agent = "architect"
    elif re.search(r"\b(claude|pair)\b", text):
        target_agent = "claude"
    elif re.search(r"\b(default|global|system)\b", text):
        target_agent = "default"

    # 6. Assignment commands: "set voice to Christopher", "switch to Aria", "make my voice Sonia", "choose William"
    assign_match = re.search(
        r"\b(set|switch|change|make|choose|select|assign|use|pick)\b", text
    )
    if assign_match and target_persona_name:
        p_id = target_persona_obj.id if target_persona_obj else target_persona_name
        provider = target_persona_obj.provider if target_persona_obj else "edge_tts"

        if target_agent == "default":
            config.tts.voice = p_id
            config.tts.provider = provider
        elif target_agent in ("researcher", "debugger", "architect"):
            config.subagents[target_agent] = AgentVoiceProfile(
                voice=p_id,
                provider=provider,
                description=f"Assigned to {target_agent}",
            )
        else:
            config.agents[target_agent] = AgentVoiceProfile(
                voice=p_id,
                provider=provider,
                description=f"Assigned to {target_agent}",
            )

        save_config(config)
        agent_label = "your main agent" if target_agent == "antigravity" else f"subagent {target_agent}"
        return {
            "action": "assign",
            "target": target_agent,
            "voice": target_persona_name,
            "voice_id": p_id,
            "provider": provider,
            "message": f"Successfully set {agent_label} voice to {target_persona_name}",
            "speech_feedback": f"Voice for {agent_label} is now set to {target_persona_name}.",
        }

    # 7. Audition / Test commands: "audition Christopher", "test Aria", "play Sonia", "hear William"
    audition_match = re.search(
        r"\b(audition|test|play|hear|listen|preview|sample)\b", text
    )
    if (audition_match or "how does" in text) and target_persona_name:
        p_id = target_persona_obj.id if target_persona_obj else target_persona_name
        sample_text = (
            target_persona_obj.sample_text
            if target_persona_obj
            else f"Hello! This is {target_persona_name} auditioning for Voicegency."
        )
        provider = target_persona_obj.provider if target_persona_obj else "edge_tts"

        return {
            "action": "audition",
            "voice": target_persona_name,
            "voice_id": p_id,
            "provider": provider,
            "sample_text": sample_text,
            "message": f"Auditioning {target_persona_name}",
            "speech_feedback": None,
        }

    # 8. Unhandled or partial voice name mentioned
    if target_persona_name:
        return {
            "action": "audition",
            "voice": target_persona_name,
            "voice_id": target_persona_obj.id if target_persona_obj else target_persona_name,
            "provider": target_persona_obj.provider if target_persona_obj else "edge_tts",
            "sample_text": target_persona_obj.sample_text if target_persona_obj else f"Hello, I am {target_persona_name}.",
            "message": f"Recognized persona {target_persona_name}. Playing sample.",
        }

    return {
        "action": "unknown",
        "message": f"Unrecognized voice command: '{command_text}'. Try saying 'Audition Christopher' or 'Set voice to Aria'.",
        "speech_feedback": "I didn't quite catch that. You can say 'Audition Christopher' or 'Switch voice to Aria'.",
    }


def get_current_system_state(config: VoicegencyConfig) -> Dict[str, Any]:
    """Compile comprehensive state for the UI frontend."""
    # Active voice for Antigravity
    ag_prov, ag_voice, ag_rate = config.resolve_voice("antigravity")
    ag_name = None
    try:
        from voicegency.tts.cloning import VoiceCloneManager
        for c in VoiceCloneManager().list_cloned_voices():
            if ag_voice in (c.id, c.name, c.calibrated_voice) and "antigravity" in c.assigned_agents:
                ag_name = c.name
                break
    except Exception:
        pass

    if not ag_name:
        ag_persona = find_persona(ag_voice)
        ag_name = ag_persona.name if ag_persona else ag_voice

    # Active voice mappings for subagents
    subagents_state = {}
    for role, profile in config.subagents.items():
        p = find_persona(profile.voice)
        subagents_state[role] = {
            "voice": profile.voice,
            "name": p.name if p else profile.voice,
            "provider": profile.provider or config.tts.provider,
            "rate": profile.rate or config.tts.rate,
        }

    # Agents state
    agents_state = {}
    for aname, profile in config.agents.items():
        p = find_persona(profile.voice)
        agents_state[aname] = {
            "voice": profile.voice,
            "name": p.name if p else profile.voice,
            "provider": profile.provider or config.tts.provider,
            "rate": profile.rate or config.tts.rate,
        }

    # Curated personas
    curated = [
        {
            "id": cp.id,
            "name": cp.name,
            "provider": cp.provider,
            "gender": cp.gender,
            "locale": cp.locale,
            "style": cp.style,
            "sample_text": cp.sample_text,
            "recommended_role": cp.recommended_role,
        }
        for cp in CURATED_PERSONAS
    ]

    all_voices = list_all_available_voices()

    # Cloned voices
    try:
        from voicegency.tts.cloning import VoiceCloneManager
        cloned_voices = [c.model_dump() for c in VoiceCloneManager().list_cloned_voices()]
    except Exception:
        cloned_voices = []

    return {
        "config": {
            "tts": config.tts.model_dump(),
            "vad": config.vad.model_dump(),
            "antigravity": config.antigravity.model_dump(),
        },
        "active_antigravity": {
            "name": ag_name,
            "voice": ag_voice,
            "provider": ag_prov,
            "rate": ag_rate,
        },
        "agents": agents_state,
        "subagents": subagents_state,
        "curated_personas": curated,
        "cloned_voices": cloned_voices,
        "all_voices": all_voices,
    }


HTML_CONTROL_PANEL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Voicegency • Voice Control Panel</title>
  <style>
    :root {
      --bg-color: #f8fafc;
      --bg-surface: #ffffff;
      --card-bg: #ffffff;
      --card-border: #e2e8f0;
      --card-hover-border: #cbd5e1;
      --card-hover-bg: #ffffff;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-subtle: #eff6ff;
      --accent-border: #bfdbfe;
      --green: #059669;
      --green-hover: #047857;
      --green-subtle: #ecfdf5;
      --green-border: #a7f3d0;
      --text: #0f172a;
      --text-secondary: #334155;
      --text-muted: #64748b;
      --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
      --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.07), 0 2px 4px -2px rgb(0 0 0 / 0.05);
      --shadow-lg: 0 10px 20px -3px rgb(0 0 0 / 0.08), 0 4px 6px -4px rgb(0 0 0 / 0.04);
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: var(--font-sans);
      background: var(--bg-color);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 32px 20px 60px;
      overflow-x: hidden;
      -webkit-font-smoothing: antialiased;
    }

    .container {
      width: 100%;
      max-width: 1100px;
    }

    /* Header */
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 28px;
    }

    .logo-group {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    .logo-icon {
      font-size: 30px;
      background: var(--accent-subtle);
      border: 1px solid var(--accent-border);
      width: 52px;
      height: 52px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 14px;
      box-shadow: var(--shadow-sm);
    }

    .logo-text h1 {
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .logo-text p {
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 2px;
    }

    .badge-patent {
      font-size: 10px;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      padding: 2px 6px;
      border-radius: 4px;
      color: var(--text-secondary);
      font-weight: 600;
    }

    .header-actions {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    /* Voice Command Mic Button */
    .mic-button {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 10px 20px;
      border-radius: 30px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
      transition: all 0.2s ease;
    }

    .mic-button:hover {
      background: var(--accent-hover);
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
    }

    .mic-button.listening {
      background: #ef4444;
      animation: pulse-red 1.5s infinite;
      box-shadow: 0 0 16px rgba(239, 68, 68, 0.5);
    }

    @keyframes pulse-red {
      0% { transform: scale(1); }
      50% { transform: scale(1.04); }
      100% { transform: scale(1); }
    }

    .btn-stop-audio {
      background: #ffffff;
      border: 1px solid var(--card-border);
      color: var(--text-secondary);
      padding: 10px 16px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      box-shadow: var(--shadow-sm);
      transition: all 0.15s ease;
    }

    .btn-stop-audio:hover {
      background: #f8fafc;
      border-color: #cbd5e1;
      color: var(--text);
    }

    /* Voice Command HUD Banner */
    .voice-hud {
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      border-radius: 14px;
      padding: 16px 20px;
      margin-bottom: 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      box-shadow: var(--shadow-sm);
    }

    .hud-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .hud-icon {
      font-size: 24px;
      animation: bounce 2s infinite;
    }

    @keyframes bounce {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-3px); }
    }

    .hud-title {
      font-size: 14px;
      font-weight: 600;
      color: #166534;
    }

    .hud-transcript {
      font-size: 13px;
      color: #15803d;
      font-family: monospace;
      margin-top: 2px;
      font-weight: 600;
    }

    .hud-hints {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .hint-chip {
      background: #ffffff;
      border: 1px solid #bbf7d0;
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 500;
      color: #166534;
      cursor: pointer;
      box-shadow: var(--shadow-sm);
      transition: all 0.15s ease;
    }

    .hint-chip:hover {
      background: #dcfce7;
      border-color: #86efac;
      transform: translateY(-1px);
    }

    /* Target Selector Tabs */
    .target-tabs {
      display: flex;
      gap: 8px;
      background: #f1f5f9;
      padding: 6px;
      border-radius: 12px;
      border: 1px solid var(--card-border);
      margin-bottom: 24px;
      overflow-x: auto;
    }

    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-secondary);
      padding: 9px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
      transition: all 0.15s ease;
    }

    .tab-btn:hover {
      color: var(--text);
      background: rgba(255, 255, 255, 0.6);
    }

    .tab-btn.active {
      background: var(--accent);
      color: #ffffff;
      box-shadow: var(--shadow-sm);
    }

    .tab-badge {
      font-size: 11px;
      padding: 2px 7px;
      background: rgba(0, 0, 0, 0.08);
      border-radius: 12px;
      font-weight: 600;
    }

    .tab-btn.active .tab-badge {
      background: rgba(255, 255, 255, 0.25);
      color: #ffffff;
    }

    /* Active Persona Banner */
    .active-banner {
      background: var(--accent-subtle);
      border: 1px solid var(--accent-border);
      border-radius: 14px;
      padding: 18px 22px;
      margin-bottom: 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: var(--shadow-sm);
    }

    .active-banner-left {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    .active-avatar {
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: var(--accent);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      font-weight: 700;
      color: white;
      box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
    }

    .active-info h3 {
      font-size: 16px;
      font-weight: 700;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .active-info p {
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 2px;
    }

    .btn-team-showcase {
      background: var(--green-subtle);
      border: 1px solid var(--green-border);
      color: var(--green);
      padding: 9px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      box-shadow: var(--shadow-sm);
      transition: all 0.15s ease;
    }

    .btn-team-showcase:hover {
      background: #d1fae5;
      transform: translateY(-1px);
    }

    /* Grid of Curated Personas */
    .section-title {
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .persona-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }

    .persona-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      box-shadow: var(--shadow-sm);
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      position: relative;
      overflow: hidden;
    }

    .persona-card:hover {
      border-color: var(--card-hover-border);
      transform: translateY(-2px);
      box-shadow: var(--shadow-lg);
    }

    .persona-card.active-selected {
      border-color: var(--green);
      background: #fcfdfd;
      box-shadow: 0 0 0 2px var(--green-border), var(--shadow-md);
    }

    .card-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }

    .avatar {
      width: 42px;
      height: 42px;
      border-radius: 12px;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
    }

    .persona-name-group h4 {
      font-size: 16px;
      font-weight: 700;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .badge-tag {
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 4px;
      font-weight: 600;
    }

    .badge-edge { background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
    .badge-mac { background: #fce7f3; color: #be185d; border: 1px solid #fbcfe8; }
    .badge-role { background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; }
    .badge-clone { background: #ede9fe; color: #6d28d9; border: 1px solid #ddd6fe; }

    .persona-style {
      font-size: 13px;
      color: var(--text-secondary);
      line-height: 1.4;
      margin-bottom: 10px;
      min-height: 34px;
    }

    .persona-sample-box {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 9px 12px;
      font-size: 12px;
      color: var(--text-muted);
      font-style: italic;
      margin-bottom: 12px;
      line-height: 1.4;
    }

    .card-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #f1f5f9;
    }

    .btn-audition {
      background: #ffffff;
      border: 1px solid #cbd5e1;
      color: var(--text);
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      box-shadow: var(--shadow-sm);
      transition: all 0.15s ease;
      user-select: none;
    }

    .btn-audition:hover {
      background: #f8fafc;
      border-color: #94a3b8;
      transform: translateY(-1px);
    }

    .btn-select {
      background: var(--accent);
      border: none;
      color: white;
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      box-shadow: var(--shadow-sm);
      transition: all 0.15s ease;
      flex: 1;
      user-select: none;
    }

    .btn-select:hover {
      background: var(--accent-hover);
      box-shadow: var(--shadow-md);
      transform: translateY(-1px);
    }

    .btn-select.selected {
      background: var(--green);
      cursor: default;
    }

    .waveform {
      display: none;
      align-items: center;
      gap: 3px;
      height: 16px;
      margin-right: 4px;
    }

    .waveform.playing {
      display: flex;
    }

    .waveform .bar, .bar {
      width: 3px;
      background: var(--accent);
      border-radius: 2px;
      animation: wave 0.8s infinite ease-in-out alternate;
    }

    .bar:nth-child(1) { height: 6px; animation-delay: 0.1s; }
    .bar:nth-child(2) { height: 14px; animation-delay: 0.3s; }
    .bar:nth-child(3) { height: 10px; animation-delay: 0.2s; }
    .bar:nth-child(4) { height: 16px; animation-delay: 0.4s; }

    @keyframes wave {
      0% { transform: scaleY(0.3); }
      100% { transform: scaleY(1); }
    }

    /* Voice Trainer & Cloning Box */
    .trainer-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 24px;
      margin-bottom: 32px;
      box-shadow: var(--shadow-sm);
    }

    .trainer-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }

    @media (max-width: 768px) {
      .trainer-grid { grid-template-columns: 1fr; }
    }

    .input-field {
      width: 100%;
      padding: 9px 12px;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      font-size: 13px;
      margin-bottom: 12px;
      outline: none;
      font-family: inherit;
    }

    .input-field:focus {
      border-color: #7c3aed;
      box-shadow: 0 0 0 2px #ede9fe;
    }

    .prompt-reader-card {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
    }

    .prompt-step-badge {
      font-size: 11px;
      font-weight: 700;
      color: #7c3aed;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 6px;
    }

    .prompt-text {
      font-size: 13px;
      font-weight: 500;
      color: var(--text);
      line-height: 1.5;
      margin-bottom: 12px;
    }

    .record-controls {
      display: flex;
      gap: 10px;
      align-items: center;
    }

    .btn-record {
      background: #ef4444;
      color: #fff;
      border: none;
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }

    .btn-record.recording {
      background: #dc2626;
      animation: pulse-red 1.2s infinite;
    }

    .btn-train-submit {
      background: #7c3aed;
      color: #fff;
      border: none;
      padding: 10px 20px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      width: 100%;
      box-shadow: 0 2px 8px rgba(124, 58, 237, 0.25);
      transition: all 0.2s;
    }

    .btn-train-submit:hover {
      background: #6d28d9;
      transform: translateY(-1px);
    }

    .samples-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 6px;
    }

    .sample-chip {
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .btn-delete-clone {
      background: transparent;
      border: none;
      color: #ef4444;
      cursor: pointer;
      font-size: 11px;
      font-weight: 600;
      padding: 4px;
    }

    .btn-delete-clone:hover {
      text-decoration: underline;
    }

    /* Sandbox / Tuning Section */
    .tuning-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 22px;
      margin-bottom: 32px;
      box-shadow: var(--shadow-sm);
    }


    .tuning-grid {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 24px;
    }

    @media (max-width: 768px) {
      .tuning-grid { grid-template-columns: 1fr; }
    }

    .custom-text-input {
      width: 100%;
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      padding: 12px 14px;
      color: var(--text);
      font-size: 13px;
      font-family: inherit;
      resize: vertical;
      min-height: 75px;
      margin-bottom: 10px;
    }

    .custom-text-input:focus {
      outline: none;
      background: #ffffff;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
    }

    .slider-group {
      margin-bottom: 14px;
    }

    .slider-header {
      display: flex;
      justify-content: space-between;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 8px;
      color: var(--text-secondary);
    }

    .range-slider {
      width: 100%;
      accent-color: var(--accent);
    }

    /* Toast Notification */
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #0f172a;
      border: 1px solid #334155;
      color: #ffffff;
      padding: 12px 20px;
      border-radius: 10px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
      font-size: 14px;
      font-weight: 500;
      transform: translateY(100px);
      opacity: 0;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      z-index: 9999;
      display: flex;
      align-items: center;
      gap: 8px;
      pointer-events: none;
    }

    .toast.show {
      transform: translateY(0);
      opacity: 1;
      pointer-events: auto;
    }
  </style>
</head>
<body>

<div class="container">

  <!-- Header -->
  <header>
    <div class="logo-group">
      <div class="logo-icon">🎙️</div>
      <div class="logo-text">
        <h1>Voicegency Control Panel <span class="badge-patent">Patent Pending</span></h1>
        <p>Acoustic Personas, Voice Auditions & Hands-Free Multi-Agent Voice Control</p>
      </div>
    </div>
    <div class="header-actions">
      <button id="micBtn" class="mic-button" onclick="toggleVoiceCommand()">
        <span id="micIcon">🎤</span> <span id="micLabel">Voice Control</span>
      </button>
      <button class="btn-stop-audio" onclick="stopSpeech()">🛑 Stop Speech (Esc)</button>
    </div>
  </header>

  <!-- Voice Control Live HUD -->
  <div class="voice-hud" id="voiceHud">
    <div class="hud-left">
      <div class="hud-icon">🗣️</div>
      <div>
        <div class="hud-title">Voice Control Active • Speak any command:</div>
        <div class="hud-transcript" id="hudTranscript">"Audition Christopher" or "Switch my voice to Aria"</div>
      </div>
    </div>
    <div class="hud-hints">
      <span class="hint-chip" onclick="speakHint('Audition Christopher')">🗣️ Audition Christopher</span>
      <span class="hint-chip" onclick="speakHint('Switch to Aria')">🗣️ Switch to Aria</span>
      <span class="hint-chip" onclick="speakHint('Assign Sonia to researcher')">🗣️ Make researcher Sonia</span>
      <span class="hint-chip" onclick="speakHint('Faster')">🗣️ Faster</span>
      <span class="hint-chip" onclick="speakHint('Stop')">🗣️ Stop</span>
    </div>
  </div>

  <!-- Target Agent Selector Tabs -->
  <div class="target-tabs" id="targetTabs">
    <button class="tab-btn active" id="tab-antigravity" onclick="setTarget('antigravity', this)">
      🤖 Antigravity (Main Agent) <span class="tab-badge" id="badge-antigravity">Christopher</span>
    </button>
    <button class="tab-btn" id="tab-researcher" onclick="setTarget('researcher', this)">
      🔍 Researcher <span class="tab-badge" id="badge-researcher">Sonia</span>
    </button>
    <button class="tab-btn" id="tab-debugger" onclick="setTarget('debugger', this)">
      🐞 Debugger / QA <span class="tab-badge" id="badge-debugger">Aria</span>
    </button>
    <button class="tab-btn" id="tab-architect" onclick="setTarget('architect', this)">
      📐 Architect <span class="tab-badge" id="badge-architect">William</span>
    </button>
    <button class="tab-btn" id="tab-default" onclick="setTarget('default', this)">
      🌐 Global Default TTS <span class="tab-badge" id="badge-default">Samantha</span>
    </button>
  </div>

  <!-- Active Persona Highlight Banner -->
  <div class="active-banner">
    <div class="active-banner-left">
      <div class="active-avatar" id="activeAvatar">C</div>
      <div class="active-info">
        <h3 id="activeTitle">Configuring Antigravity: Christopher</h3>
        <p id="activeSubtitle">Deep, grounded, authoritative neural voice • Edge TTS</p>
      </div>
    </div>
    <div>
      <button class="btn-team-showcase" onclick="playShowcase()">
        🎭 Audition All Agents (Team Showcase)
      </button>
    </div>
  </div>

  <!-- Curated Persona Cards Grid -->
  <div class="section-title">
    <span>Curated Acoustic Personas</span>
    <span style="font-size: 13px; color: var(--text-muted); font-weight: normal;">Click audition to hear sample over your speakers</span>
  </div>

  <div class="persona-grid" id="personaGrid">
    <!-- Populated dynamically via JS -->
  </div>

  <!-- Custom Cloned Voices Grid (if any) -->
  <div id="clonedSection" style="display: none; margin-bottom: 28px;">
    <div class="section-title">
      <span>🎙️ Your Custom Cloned Voices</span>
      <span style="font-size: 13px; color: #7c3aed; font-weight: 600;">Trained on your speech</span>
    </div>
    <div class="persona-grid" id="clonedGrid">
      <!-- Populated dynamically via JS -->
    </div>
  </div>

  <!-- Voice Training & Cloning Studio -->
  <div class="trainer-box">
    <div class="section-title">
      <span>🎙️ Train & Clone Your Voice ("Talk Like Me")</span>
      <span style="font-size: 13px; color: #7c3aed; font-weight: 600;">ElevenLabs IVC + Local Acoustic Profiling</span>
    </div>
    <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 18px; line-height: 1.4;">
      Record sample phrases or import audio recordings to calibrate your personal acoustic profile, extract vocal pitch & cadence, and generate an AI persona that speaks and acts like you.
    </p>
    <div class="trainer-grid">
      <div>
        <label style="font-size: 13px; font-weight: 600; margin-bottom: 6px; display: block;">Voice Profile Name:</label>
        <input type="text" id="cloneName" class="input-field" placeholder="e.g. Jake, Alex, Founder..." />

        <label style="font-size: 13px; font-weight: 600; margin-bottom: 6px; display: block;">ElevenLabs API Key (Optional):</label>
        <input type="password" id="cloneApiKey" class="input-field" placeholder="xi-api-key (Leave blank for offline local calibration)" />

        <label style="font-size: 13px; font-weight: 600; margin-bottom: 6px; display: block;">Persona Tone & Conversational Style:</label>
        <input type="text" id="cloneTone" class="input-field" placeholder="e.g. pragmatic, focused, developer-centric" value="pragmatic, focused, developer-centric" />

        <label style="font-size: 13px; font-weight: 600; margin-bottom: 6px; display: block;">Import Existing Audio Files (.wav, .mp3):</label>
        <input type="file" id="cloneFileInput" multiple accept="audio/*" class="input-field" onchange="handleAudioFilesSelected(this)" />
      </div>

      <div>
        <div class="prompt-reader-card">
          <div class="prompt-step-badge" id="promptStepBadge">Training Prompt 1 of 4: Conversational Intro</div>
          <div class="prompt-text" id="promptText">"Hey there! I am recording my voice so my AI coding agents can pair program and talk with me in real-time."</div>
          
          <div class="record-controls">
            <button id="btnRecordSample" class="btn-record" onclick="toggleSampleRecording()">
              🔴 Record Sample
            </button>
            <button class="btn-audition" style="width: auto;" onclick="nextTrainingPrompt()">
              Next Prompt ⏭️
            </button>
          </div>
        </div>

        <div style="font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 4px;">Captured Training Samples (<span id="sampleCount">0</span>):</div>
        <div class="samples-chips" id="samplesContainer">
          <span style="font-size: 12px; color: var(--text-muted); font-style: italic;">No samples recorded yet. Click 'Record Sample' or select files.</span>
        </div>

        <div style="margin-top: 16px;">
          <button class="btn-train-submit" id="btnTrainSubmit" onclick="submitVoiceTraining()">
            ✨ Train & Clone Voice Now
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Live Testing Sandbox & Speed Controls -->
  <div class="tuning-box">
    <div class="section-title">🎙️ Live Testing Sandbox & Speech Parameters</div>
    <div class="tuning-grid">
      <div>
        <label style="font-size: 13px; color: var(--text-muted); margin-bottom: 6px; display: block;">Custom Audition Text:</label>
        <textarea id="customSampleText" class="custom-text-input" placeholder="Type custom text here to hear how your selected voice pronounces it...">Hey! I'm your active voice assistant. Ready to build something great together.</textarea>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <button class="btn-audition" style="width: auto; padding: 8px 18px;" onclick="testCustomSample()">
            ▶ Test Selected Voice
          </button>
          <button class="btn-audition" style="width: auto; padding: 8px 18px; background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8;" onclick="previewNativeHUD()">
            ✨ Preview Native macOS Pop-up (HUD)
          </button>
        </div>
      </div>
      <div>
        <div class="slider-group">
          <div class="slider-header">
            <span>Speech Speed / Rate</span>
            <span id="rateLabel">200 WPM</span>
          </div>
          <input type="range" min="120" max="320" value="200" step="10" class="range-slider" id="rateSlider" oninput="updateRate(this.value)">
        </div>
        <p style="font-size: 12px; color: var(--text-muted); line-height: 1.4;">
          Tip: You can also say <b>"Faster"</b> or <b>"Slower"</b> at any time using voice control.
        </p>
      </div>
    </div>
  </div>

</div>

<!-- Toast notification popup -->
<div id="toast" class="toast">✅ Voice updated successfully!</div>

<script>
  let state = null;
  let currentTarget = 'antigravity';
  let isListening = false;
  let recognition = null;

  // Training state
  let trainingPrompts = [
    { title: "Conversational Intro", text: "Hey there! I am recording my voice so my AI coding agents can pair program and talk with me in real-time." },
    { title: "Technical & Code Flow", text: "Antigravity, let's refactor the asynchronous database connection pool and run the complete test suite." },
    { title: "Decisions & Architecture", text: "The architecture looks clean. Let's merge the branch, tag release version one point zero, and deploy to production." },
    { title: "Quick Confirmation", text: "Got it. All unit tests passed without errors, everything looks solid and ready to ship." }
  ];
  let currentPromptIdx = 0;
  let capturedSamples = []; // { filename, data (base64) }
  let mediaRecorder = null;
  let audioChunks = [];
  let isRecordingSample = false;

  // Personas avatars
  const avatarIcons = {
    'Christopher': '🧔',
    'Aria': '⚡',
    'Sonia': '🔍',
    'Guy': '☕',
    'William': '🦘',
    'Jenny': '👩‍💻',
    'Samantha': '🍎',
    'Alex': '🍏'
  };

  async function fetchState() {
    try {
      const res = await fetch('/api/state');
      state = await res.json();
      renderUI();
    } catch (e) {
      console.error('Failed to fetch state:', e);
    }
  }

  function getActiveVoiceForTarget(target) {
    if (!state) return 'Christopher';
    if (target === 'antigravity') {
      if (state.active_antigravity) {
        if (typeof state.active_antigravity === 'string') return state.active_antigravity;
        return state.active_antigravity.name || state.active_antigravity.voice || 'Christopher';
      }
      return 'Christopher';
    }
    if (target === 'default') {
      return state.config?.tts?.voice || 'Samantha';
    }
    if (state.subagents && state.subagents[target]) {
      const s = state.subagents[target];
      return typeof s === 'string' ? s : (s.name || s.voice || 'Sonia');
    }
    if (state.agents && state.agents[target]) {
      const a = state.agents[target];
      return typeof a === 'string' ? a : (a.name || a.voice || 'Christopher');
    }
    return state.config?.tts?.voice || 'Samantha';
  }

  function setTarget(target, btnElem) {
    currentTarget = target;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    if (btnElem) {
      btnElem.classList.add('active');
    } else {
      const b = document.getElementById(`tab-${target}`);
      if (b) b.classList.add('active');
    }
    renderActiveBanner();
    renderCards();
  }

  function renderActiveBanner() {
    const activeName = getActiveVoiceForTarget(currentTarget) || 'Christopher';
    const persona = state?.curated_personas?.find(p => p.name === activeName || p.id === activeName);
    const clone = state?.cloned_voices?.find(c => c.name === activeName || c.id === activeName);
    
    const avatarEl = document.getElementById('activeAvatar');
    const titleEl = document.getElementById('activeTitle');
    const subEl = document.getElementById('activeSubtitle');

    if (avatarEl) {
      avatarEl.textContent = avatarIcons[activeName] || (clone ? '🎙️' : (activeName ? activeName.charAt(0) : '🎙️'));
    }
    if (titleEl) {
      titleEl.textContent = `Configuring ${formatTarget(currentTarget)}: ${activeName}`;
    }
    if (subEl) {
      if (clone) {
        const vr = clone.acoustic_metrics?.vocal_range || 'Custom Voice Clone';
        subEl.textContent = `Custom Trained Voice (${vr}) • ${clone.provider.toUpperCase()}`;
      } else if (persona) {
        subEl.textContent = `${persona.style} • ${persona.provider.replace('_', ' ').toUpperCase()} (${persona.locale})`;
      } else {
        subEl.textContent = `Custom Voice (${activeName})`;
      }
    }
  }

  function formatTarget(target) {
    if (target === 'antigravity') return 'Antigravity (Main Agent)';
    if (target === 'researcher') return 'Researcher Subagent';
    if (target === 'debugger') return 'Debugger / QA Subagent';
    if (target === 'architect') return 'Architect Subagent';
    if (target === 'default') return 'Global Default TTS';
    return target;
  }

  function renderCards() {
    if (!state) return;
    const activeVoice = getActiveVoiceForTarget(currentTarget);

    // 1. Curated Grid
    const grid = document.getElementById('personaGrid');
    if (state.curated_personas) {
      grid.innerHTML = state.curated_personas.map(p => {
        const isSelected = (p.name.toLowerCase() === activeVoice.toLowerCase() || p.id.toLowerCase() === activeVoice.toLowerCase());
        const providerClass = p.provider === 'edge_tts' ? 'badge-edge' : 'badge-mac';
        const providerLabel = p.provider === 'edge_tts' ? 'Edge Neural' : 'macOS Native';

        return `
          <div class="persona-card ${isSelected ? 'active-selected' : ''}" id="card-${p.name}">
            <div>
              <div class="card-header">
                <div class="avatar">${avatarIcons[p.name] || '🎙️'}</div>
                <div class="persona-name-group">
                  <h4>${p.name} <span class="badge-tag ${providerClass}">${providerLabel}</span></h4>
                  <span class="badge-tag badge-role">${p.recommended_role}</span>
                </div>
              </div>
              <div class="persona-style">${p.style}</div>
              <div class="persona-sample-box">"${p.sample_text}"</div>
            </div>
            <div class="card-actions">
              <div class="waveform" id="wave-${p.name}">
                <div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div>
              </div>
              <button class="btn-audition" onclick="auditionVoice('${p.name}', '${p.id}', '${p.provider}')">
                ▶ Audition
              </button>
              <button class="btn-select ${isSelected ? 'selected' : ''}" onclick="selectVoice('${p.name}', '${p.id}', '${p.provider}')">
                ${isSelected ? '✓ Active' : 'Set Voice'}
              </button>
            </div>
          </div>
        `;
      }).join('');
    }

    // 2. Cloned Voices Grid
    const clonedSection = document.getElementById('clonedSection');
    const clonedGrid = document.getElementById('clonedGrid');
    if (state.cloned_voices && state.cloned_voices.length > 0) {
      clonedSection.style.display = 'block';
      clonedGrid.innerHTML = state.cloned_voices.map(c => {
        const isSelected = (c.name.toLowerCase() === activeVoice.toLowerCase() || c.id.toLowerCase() === activeVoice.toLowerCase());
        const vRange = c.acoustic_metrics?.vocal_range || 'Custom Timbre';
        const pitchHz = c.acoustic_metrics?.avg_pitch_hz ? `${c.acoustic_metrics.avg_pitch_hz} Hz` : '';
        const dur = c.acoustic_metrics?.total_duration_seconds ? `${c.acoustic_metrics.total_duration_seconds}s audio` : '';

        return `
          <div class="persona-card ${isSelected ? 'active-selected' : ''}" id="card-${c.name}">
            <div>
              <div class="card-header">
                <div class="avatar" style="background: #ede9fe; color: #6d28d9; border-color: #ddd6fe;">🎙️</div>
                <div class="persona-name-group">
                  <h4>${c.name} <span class="badge-tag badge-clone">Custom Clone</span></h4>
                  <span class="badge-tag badge-role">${vRange} ${pitchHz ? '• ' + pitchHz : ''}</span>
                </div>
              </div>
              <div class="persona-style">${c.description || 'Trained on user voice samples.'} (${dur})</div>
              <div class="persona-sample-box">"Hey there! This is ${c.name}, speaking with my custom cloned voice."</div>
            </div>
            <div class="card-actions">
              <div class="waveform" id="wave-${c.name}">
                <div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div>
              </div>
              <button class="btn-audition" onclick="auditionVoice('${c.name}', '${c.id}', '${c.provider}')">
                ▶ Audition
              </button>
              <button class="btn-select ${isSelected ? 'selected' : ''}" onclick="selectVoice('${c.name}', '${c.id}', '${c.provider}')">
                ${isSelected ? '✓ Active' : 'Set Voice'}
              </button>
              <button class="btn-delete-clone" onclick="deleteVoiceClone('${c.name}')" title="Delete voice profile">
                🗑️
              </button>
            </div>
          </div>
        `;
      }).join('');
    } else {
      clonedSection.style.display = 'none';
    }

    // Update badges on tabs
    if (document.getElementById('badge-antigravity')) {
      document.getElementById('badge-antigravity').textContent = getActiveVoiceForTarget('antigravity');
      document.getElementById('badge-researcher').textContent = getActiveVoiceForTarget('researcher');
      document.getElementById('badge-debugger').textContent = getActiveVoiceForTarget('debugger');
      document.getElementById('badge-architect').textContent = getActiveVoiceForTarget('architect');
      document.getElementById('badge-default').textContent = getActiveVoiceForTarget('default');
    }
  }

  function renderUI() {
    renderActiveBanner();
    renderCards();
    if (state?.config?.tts?.rate) {
      document.getElementById('rateSlider').value = state.config.tts.rate;
      document.getElementById('rateLabel').textContent = `${state.config.tts.rate} WPM`;
    }
  }

  // Training Stepper & Recorder Logic
  function updatePromptUI() {
    const p = trainingPrompts[currentPromptIdx];
    document.getElementById('promptStepBadge').textContent = `Training Prompt ${currentPromptIdx + 1} of ${trainingPrompts.length}: ${p.title}`;
    document.getElementById('promptText').textContent = `"${p.text}"`;
  }

  function nextTrainingPrompt() {
    currentPromptIdx = (currentPromptIdx + 1) % trainingPrompts.length;
    updatePromptUI();
  }

  async function toggleSampleRecording() {
    const btn = document.getElementById('btnRecordSample');
    const p = trainingPrompts[currentPromptIdx];

    if (btn.classList.contains('recording')) {
      return;
    }

    btn.classList.add('recording');
    btn.textContent = '🎙️ Listening... (Speak now)';
    showToast(`🎙️ Speak now: "${p.text}"`);

    try {
      const res = await fetch('/api/clone/record_mic', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_title: p.title })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        capturedSamples.push({
          filename: data.filename,
          data: data.data
        });
        renderSamplesList();
        showToast(`✅ Captured ${data.filename} (${data.duration}s)!`);
        nextTrainingPrompt();
      } else {
        showToast(`⚠️ Mic: ${data.error || 'Trying browser recorder...'}`);
        await recordSampleViaBrowser();
      }
    } catch (e) {
      console.warn('Backend record error, trying browser:', e);
      await recordSampleViaBrowser();
    } finally {
      btn.classList.remove('recording');
      btn.textContent = '🔴 Record Sample';
    }
  }

  async function recordSampleViaBrowser() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast('⚠️ No microphone detected. You can select an audio file below.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunks = [];
      const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
      mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(audioChunks, { type: mimeType || 'audio/wav' });
        const reader = new FileReader();
        reader.readAsDataURL(blob);
        reader.onloadend = () => {
          const sampleNum = capturedSamples.length + 1;
          capturedSamples.push({
            filename: `browser_sample_${sampleNum}.wav`,
            data: reader.result
          });
          renderSamplesList();
          showToast(`✅ Captured sample ${sampleNum}!`);
          nextTrainingPrompt();
        };
        stream.getTracks().forEach(t => t.stop());
      };

      mediaRecorder.start();
      setTimeout(() => {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
          mediaRecorder.stop();
        }
      }, 4000);
    } catch (err) {
      showToast('⚠️ Browser mic error: ' + err.message);
    }
  }


  function handleAudioFilesSelected(input) {
    if (!input.files || input.files.length === 0) return;
    Array.from(input.files).forEach(file => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onloadend = () => {
        capturedSamples.push({
          filename: file.name,
          data: reader.result
        });
        renderSamplesList();
      };
    });
    showToast(`📥 Added ${input.files.length} audio sample files.`);
  }

  function renderSamplesList() {
    const container = document.getElementById('samplesContainer');
    document.getElementById('sampleCount').textContent = capturedSamples.length;
    if (capturedSamples.length === 0) {
      container.innerHTML = '<span style="font-size: 12px; color: var(--text-muted); font-style: italic;">No samples recorded yet. Click &quot;Record Sample&quot; or select files.</span>';
      return;
    }
    container.innerHTML = capturedSamples.map((s, idx) => `
      <div class="sample-chip">
        <span>🎵 ${s.filename}</span>
        <span style="cursor: pointer; color: #ef4444; font-weight: bold;" onclick="removeSample(${idx})">×</span>
      </div>
    `).join('');
  }

  function removeSample(idx) {
    capturedSamples.splice(idx, 1);
    renderSamplesList();
  }

  async function submitVoiceTraining() {
    const name = document.getElementById('cloneName').value.trim();
    if (!name) {
      showToast('⚠️ Please enter a Voice Profile Name.');
      document.getElementById('cloneName').focus();
      return;
    }
    if (capturedSamples.length === 0) {
      showToast('⚠️ Please record or import at least 1 audio sample.');
      return;
    }

    const apiKey = document.getElementById('cloneApiKey').value.trim();
    const tone = document.getElementById('cloneTone').value.trim();
    const btn = document.getElementById('btnTrainSubmit');

    btn.disabled = true;
    btn.textContent = '⏳ Training & Analyzing Voice...';

    try {
      const res = await fetch('/api/clone/train', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          api_key: apiKey,
          traits: { tone: tone },
          samples: capturedSamples,
          assign: currentTarget
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        showToast(`✨ Successfully trained custom voice: ${name}!`);
        capturedSamples = [];
        renderSamplesList();
        await fetchState();
      } else {
        showToast(`❌ Training failed: ${data.error || 'Unknown error'}`);
      }
    } catch (e) {
      showToast(`❌ Error: ${e}`);
    } finally {
      btn.disabled = false;
      btn.textContent = '✨ Train & Clone Voice Now';
    }
  }

  async function deleteVoiceClone(name) {
    if (!confirm(`Are you sure you want to delete custom voice clone '${name}'?`)) return;
    try {
      const res = await fetch('/api/clone/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, from_provider: true })
      });
      showToast(`🗑️ Deleted custom voice '${name}'.`);
      await fetchState();
    } catch (e) {
      showToast(`⚠️ Delete error: ${e}`);
    }
  }

  async function auditionVoice(name, voiceId, provider) {
    // Show playing waveform
    document.querySelectorAll('.waveform').forEach(w => w.classList.remove('playing'));
    const wave = document.getElementById(`wave-${name}`);
    if (wave) wave.classList.add('playing');

    try {
      await fetch('/api/audition', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice: voiceId || name, provider: provider })
      });
    } catch (e) {
      console.error(e);
    } finally {
      setTimeout(() => {
        if (wave) wave.classList.remove('playing');
      }, 3500);
    }
  }

  async function selectVoice(name, voiceId, provider) {
    try {
      const res = await fetch('/api/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: currentTarget, voice: voiceId || name, provider: provider })
      });
      const data = await res.json();
      showToast(`✅ Set ${formatTarget(currentTarget)} voice to ${name}!`);
      await fetchState();
    } catch (e) {
      showToast(`⚠️ Failed to set voice: ${e}`);
    }
  }

  async function testCustomSample() {
    const text = document.getElementById('customSampleText').value;
    const activeVoice = getActiveVoiceForTarget(currentTarget);
    const persona = state?.curated_personas?.find(p => p.name === activeVoice || p.id === activeVoice);
    const clone = state?.cloned_voices?.find(c => c.name === activeVoice || c.id === activeVoice);
    const vid = clone ? clone.id : (persona ? persona.id : activeVoice);
    const prov = clone ? clone.provider : (persona ? persona.provider : 'edge_tts');

    try {
      await fetch('/api/audition', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice: vid, provider: prov, text: text })
      });
    } catch (e) {
      console.error(e);
    }
  }

  async function previewNativeHUD() {
    const text = document.getElementById('customSampleText').value;
    const activeVoice = getActiveVoiceForTarget(currentTarget);
    showToast('✨ Triggering native macOS floating speech pop-up HUD...');
    try {
      await fetch('/api/hud/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          agent: formatTarget(currentTarget),
          persona: activeVoice
        })
      });
    } catch (e) {
      console.error(e);
      showToast('⚠️ Preview error: ' + e);
    }
  }

  async function updateRate(val) {
    document.getElementById('rateLabel').textContent = `${val} WPM`;
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rate: parseInt(val) })
      });
    } catch (e) {
      console.error(e);
    }
  }

  async function stopSpeech() {
    try {
      await fetch('/api/audition/stop', { method: 'POST' });
      document.querySelectorAll('.waveform').forEach(w => w.classList.remove('playing'));
      showToast('🛑 Speech stopped');
    } catch (e) {}
  }

  async function playShowcase() {
    showToast('🎭 Starting team voice showcase across speakers...');
    try {
      await fetch('/api/voice_command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: 'showcase' })
      });
    } catch (e) {}
  }

  // Voice Command Engine
  function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn('Web Speech API not supported in this browser. Using backend STT fallback.');
      return;
    }
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onstart = () => {
      isListening = true;
      document.getElementById('micBtn').classList.add('listening');
      document.getElementById('micLabel').textContent = 'Listening...';
      document.getElementById('hudTranscript').textContent = 'Hearing you... speak now!';
    };

    recognition.onresult = (event) => {
      let transcript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        transcript += event.results[i][0].transcript;
      }
      document.getElementById('hudTranscript').textContent = `"${transcript}"`;
      if (event.results[0].isFinal) {
        handleVoiceCommand(transcript);
      }
    };

    recognition.onerror = (e) => {
      console.error('Speech error:', e);
      resetMicUI();
    };

    recognition.onend = () => {
      resetMicUI();
    };
  }

  function resetMicUI() {
    isListening = false;
    document.getElementById('micBtn').classList.remove('listening');
    document.getElementById('micLabel').textContent = 'Voice Control';
  }

  function toggleVoiceCommand() {
    if (!recognition) {
      initSpeechRecognition();
    }
    if (recognition) {
      if (isListening) {
        recognition.stop();
        resetMicUI();
      } else {
        try {
          recognition.start();
        } catch (e) {
          recognition.stop();
        }
      }
    } else {
      // Fallback prompt
      const cmd = prompt("Enter voice command (e.g. 'Audition Christopher', 'Switch to Aria', 'Faster'):");
      if (cmd) handleVoiceCommand(cmd);
    }
  }

  async function handleVoiceCommand(cmdText) {
    document.getElementById('hudTranscript').textContent = `Processing: "${cmdText}"...`;
    try {
      const res = await fetch('/api/voice_command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmdText })
      });
      const data = await res.json();
      document.getElementById('hudTranscript').textContent = `✅ ${data.message || 'Command executed'}`;
      showToast(data.message);
      await fetchState();
    } catch (e) {
      showToast(`⚠️ Command error: ${e}`);
    }
  }

  function speakHint(hintText) {
    handleVoiceCommand(hintText);
  }

  function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3500);
  }

  // Keyboard shortcut: Space to activate voice command, Esc to stop
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      stopSpeech();
    }
  });

  // Start
  updatePromptUI();
  fetchState();
  initSpeechRecognition();
</script>

</body>
</html>
"""


class VoicePanelRequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP Request Handler for Voice Control Panel."""

    config: VoicegencyConfig

    def log_message(self, format, *args):
        # Suppress noisy standard request logs
        return

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_str: str, status: int = 200):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send_html(HTML_CONTROL_PANEL)
            return

        if path == "/api/state":
            state = get_current_system_state(self.server.config)
            self._send_json(state)
            return

        if path == "/api/voices":
            voices = list_all_available_voices()
            self._send_json(voices)
            return

        if path == "/api/clones":
            try:
                from voicegency.tts.cloning import VoiceCloneManager
                clones = [c.model_dump() for c in VoiceCloneManager().list_cloned_voices()]
                self._send_json(clones)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return

        if path == "/api/prompts":
            from voicegency.tts.cloning import TRAINING_PROMPTS
            self._send_json(TRAINING_PROMPTS)
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(body) if body.strip() else {}
        except Exception:
            payload = {}

        if path == "/api/hud/preview":
            text = payload.get("text", "I'm your active AI pairing agent. All tests passed and changes are ready to ship.")
            agent = payload.get("agent", "Antigravity")
            persona = payload.get("persona", "Christopher")
            try:
                from voicegency.ui.speech_hud import AgentSpeechHUD
                hud = AgentSpeechHUD.get_instance()
                pos = getattr(self.server.config.antigravity, "speech_popup_position", "top_center")
                hud.show_speech(text, agent_name=agent, persona_name=persona, is_speaking=True, position=pos)
                def _auto_finish():
                    time.sleep(3.5)
                    hud.finish_speech(linger_seconds=3.0)
                threading.Thread(target=_auto_finish, daemon=True).start()
                self._send_json({"status": "previewing", "text": text, "agent": agent, "persona": persona})
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return

        if path == "/api/audition":
            voice = payload.get("voice", "en-US-ChristopherNeural")
            provider = payload.get("provider")
            text = payload.get("text")
            rate = payload.get("rate")

            persona = find_persona(voice)
            if not text:
                text = persona.sample_text if persona else f"Testing voice {voice} with Voicegency."
            if not provider and persona:
                provider = persona.provider

            if getattr(self.server.config.antigravity, "show_speech_popup", True):
                try:
                    from voicegency.ui.speech_hud import AgentSpeechHUD
                    pos = getattr(self.server.config.antigravity, "speech_popup_position", "top_center")
                    AgentSpeechHUD.get_instance().show_speech(
                        text,
                        agent_name="Audition",
                        persona_name=persona.name if persona else voice,
                        is_speaking=True,
                        position=pos,
                    )
                except Exception:
                    pass

            def _speak_worker():
                try:
                    engine = get_tts_engine(
                        self.server.config,
                        voice_override=persona.id if persona else voice,
                        provider_override=provider,
                        rate_override=rate,
                    )
                    engine.speak(text, block=True)
                except Exception as e:
                    print(f"[Panel API] Audition error: {e}")
                finally:
                    if getattr(self.server.config.antigravity, "show_speech_popup", True):
                        try:
                            from voicegency.ui.speech_hud import AgentSpeechHUD
                            linger = getattr(self.server.config.antigravity, "speech_popup_linger_seconds", 2.5)
                            AgentSpeechHUD.get_instance().finish_speech(linger_seconds=linger)
                        except Exception:
                            pass

            threading.Thread(target=_speak_worker, daemon=True).start()
            self._send_json({"status": "playing", "voice": voice, "text": text})
            return

        if path == "/api/audition/stop":
            stop_all_speech()
            try:
                from voicegency.ui.speech_hud import AgentSpeechHUD
                AgentSpeechHUD.get_instance().hide()
            except Exception:
                pass
            self._send_json({"status": "stopped"})
            return

        if path == "/api/clone/record_mic":
            import base64
            from voicegency.audio.recorder import AudioRecorder
            from voicegency.audio.chimes import play_chime

            prompt_title = payload.get("prompt_title", "sample")
            config = self.server.config
            if config.audio_cues.enabled:
                play_chime("start", block=False)

            recorder = AudioRecorder(
                sample_rate=16000,
                energy_threshold=config.vad.energy_threshold,
                silence_duration=1.2,
                max_record_seconds=15,
            )

            try:
                audio_data, temp_wav = recorder.record_speech_auto()
                with open(temp_wav, "rb") as f:
                    wav_bytes = f.read()
                try:
                    temp_wav.unlink(missing_ok=True)
                except Exception:
                    pass

                b64 = base64.b64encode(wav_bytes).decode("utf-8")
                dur = round(len(audio_data) / 16000, 2)
                clean_name = "".join(c if c.isalnum() else "_" for c in prompt_title.lower())
                self._send_json({
                    "status": "success",
                    "filename": f"sample_{clean_name}_{int(time.time())}.wav",
                    "data": f"data:audio/wav;base64,{b64}",
                    "duration": dur,
                })
            except Exception as e:
                self._send_json({"error": f"Microphone capture error: {str(e)}"}, status=500)
            return

        if path == "/api/clone/train":

            import base64
            import tempfile
            from voicegency.tts.cloning import VoiceCloneManager

            name = payload.get("name", "").strip()
            if not name:
                self._send_json({"error": "Voice name is required"}, status=400)
                return

            api_key = payload.get("api_key") or self.server.config.tts.elevenlabs_api_key
            desc = payload.get("description", "")
            traits = payload.get("traits", {})
            target_agent = payload.get("assign")
            raw_samples = payload.get("samples", [])
            file_paths_in = payload.get("file_paths", [])

            temp_files = []
            try:
                sample_paths = []
                for p in file_paths_in:
                    path_obj = Path(p)
                    if path_obj.exists():
                        sample_paths.append(path_obj)

                for item in raw_samples:
                    data_b64 = item.get("data", "")
                    if "," in data_b64:
                        data_b64 = data_b64.split(",", 1)[1]
                    if data_b64:
                        audio_bytes = base64.b64decode(data_b64)
                        ext = ".wav"
                        if item.get("filename", "").endswith(".mp3"):
                            ext = ".mp3"
                        tf = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                        tf.write(audio_bytes)
                        tf.close()
                        temp_files.append(Path(tf.name))
                        sample_paths.append(Path(tf.name))

                if not sample_paths:
                    self._send_json({"error": "At least one audio sample or recording is required."}, status=400)
                    return

                manager = VoiceCloneManager()
                profile = manager.train_voice(
                    name=name,
                    sample_paths=sample_paths,
                    api_key=api_key,
                    description=desc,
                    custom_traits=traits,
                )

                if target_agent:
                    manager.assign_to_agent(profile.name, target_agent, self.server.config)

                self._send_json({
                    "status": "success",
                    "profile": profile.model_dump(),
                    "assigned": target_agent,
                })
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            finally:
                for tf in temp_files:
                    try:
                        tf.unlink(missing_ok=True)
                    except Exception:
                        pass
            return

        if path == "/api/clone/delete":
            from voicegency.tts.cloning import VoiceCloneManager
            name = payload.get("name", "")
            from_provider = payload.get("from_provider", False)
            api_key = self.server.config.tts.elevenlabs_api_key
            success = VoiceCloneManager().delete_cloned_voice(name, delete_from_elevenlabs=from_provider, api_key=api_key)
            self._send_json({"status": "success" if success else "not_found"})
            return

        if path == "/api/clone/assign":
            from voicegency.tts.cloning import VoiceCloneManager
            name = payload.get("name", "")
            target = payload.get("target", "antigravity")
            try:
                tgt, vid = VoiceCloneManager().assign_to_agent(name, target, self.server.config)
                self._send_json({"status": "success", "target": tgt, "voice_id": vid})
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if path == "/api/assign":
            target = payload.get("target", "antigravity").lower().strip()
            voice_id = payload.get("voice", "en-US-ChristopherNeural")
            provider = payload.get("provider", "edge_tts")
            rate = payload.get("rate")

            try:
                from voicegency.tts.cloning import VoiceCloneManager
                clone_mgr = VoiceCloneManager()
                clone_prof = clone_mgr.get_cloned_voice(voice_id)
                if clone_prof:
                    clone_mgr.assign_to_agent(clone_prof.name, target, self.server.config)
                    save_config(self.server.config)
                    self._send_json({"status": "success", "target": target, "voice": clone_prof.name})
                    return
            except Exception:
                pass

            persona = find_persona(voice_id)
            resolved_voice = persona.id if persona else voice_id
            resolved_provider = provider or (persona.provider if persona else "edge_tts")

            profile = AgentVoiceProfile(
                voice=resolved_voice,
                provider=resolved_provider,
                rate=rate,
                description=f"Assigned to {target}",
            )

            if target == "default":
                self.server.config.tts.voice = resolved_voice
                self.server.config.tts.provider = resolved_provider
                if rate:
                    self.server.config.tts.rate = rate
            elif target in ("researcher", "debugger", "architect", "tester", "writer"):
                self.server.config.subagents[target] = profile
            else:
                self.server.config.agents[target] = profile

            save_config(self.server.config)
            self._send_json({
                "status": "success",
                "target": target,
                "voice": resolved_voice,
                "provider": resolved_provider,
            })
            return

        if path == "/api/settings":
            if "rate" in payload:
                self.server.config.tts.rate = int(payload["rate"])
            if "provider" in payload:
                self.server.config.tts.provider = payload["provider"]
            if "voice" in payload:
                self.server.config.tts.voice = payload["voice"]
            save_config(self.server.config)
            self._send_json({"status": "saved", "config": self.server.config.tts.model_dump()})
            return

        if path == "/api/voice_command":
            cmd_text = payload.get("command", "")
            result = parse_voice_command(cmd_text, self.server.config)

            # If action is audition, trigger speech in background
            if result.get("action") == "audition":
                vid = result.get("voice_id", result.get("voice"))
                prov = result.get("provider", "edge_tts")
                stext = result.get("sample_text", "Hello from Voicegency.")

                def _audition():
                    try:
                        eng = get_tts_engine(self.server.config, voice_override=vid, provider_override=prov)
                        eng.speak(stext, block=True)
                    except Exception as e:
                        print(f"[Panel API] Audition voice command error: {e}")

                threading.Thread(target=_audition, daemon=True).start()

            elif result.get("action") == "showcase":
                def _showcase():
                    cast = [
                        ("Christopher", "en-US-ChristopherNeural", "edge_tts", "Hey! I'm Christopher. Calm and authoritative for planning."),
                        ("Aria", "en-US-AriaNeural", "edge_tts", "And I'm Aria! Energetic and crisp for test results."),
                        ("Sonia", "en-GB-SoniaNeural", "edge_tts", "I am Sonia, analytical and focused for research."),
                        ("Guy", "en-US-GuyNeural", "edge_tts", "Hey there! I'm Guy, ready for pair programming."),
                    ]
                    for name, vid, prov, txt in cast:
                        try:
                            eng = get_tts_engine(self.server.config, voice_override=vid, provider_override=prov)
                            eng.speak(txt, block=True)
                        except Exception:
                            pass
                        time.sleep(0.3)

                threading.Thread(target=_showcase, daemon=True).start()

            elif result.get("speech_feedback"):
                # Speak verbal confirmation using the newly assigned persona voice
                fb_text = result["speech_feedback"]
                target_agent = result.get("target", "antigravity")
                vid = result.get("voice_id") or result.get("voice")
                prov = result.get("provider")

                def _speak_fb():
                    try:
                        eng = get_tts_engine(
                            self.server.config,
                            agent_name=target_agent,
                            voice_override=vid,
                            provider_override=prov,
                        )
                        eng.speak(fb_text, block=True)
                    except Exception as e:
                        print(f"[Panel API] Speech feedback error: {e}")

                threading.Thread(target=_speak_fb, daemon=True).start()

            self._send_json(result)
            return

        self.send_error(404, "Endpoint not found")



class VoicePanelServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, config: VoicegencyConfig):
        super().__init__(server_address, RequestHandlerClass)
        self.config = config



_server_instance: Optional[VoicePanelServer] = None
_server_thread: Optional[threading.Thread] = None


def start_panel_server(
    port: int = 8765, config: Optional[VoicegencyConfig] = None
) -> Tuple[VoicePanelServer, int]:
    """Start local HTTP server for the Voice Control Panel."""
    global _server_instance, _server_thread
    if _server_instance:
        return _server_instance, port

    cfg = config or load_config()
    actual_port = port

    # Try requested port or fallback
    for p in range(port, port + 20):
        try:
            _server_instance = VoicePanelServer(
                ("127.0.0.1", p), VoicePanelRequestHandler, cfg
            )
            actual_port = p
            break
        except OSError:
            continue

    if not _server_instance:
        raise RuntimeError(f"Could not bind Voice Control Panel to any port starting from {port}")

    _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True)
    _server_thread.start()
    return _server_instance, actual_port


def open_control_panel(
    port: int = 8765, open_browser: bool = True, config: Optional[VoicegencyConfig] = None
) -> str:
    """Launch the Control Panel server and open in default web browser."""
    srv, actual_port = start_panel_server(port=port, config=config)
    url = f"http://localhost:{actual_port}"
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"[Voicegency] Could not automatically open browser: {e}")
    return url
