# 🎙️ VoiceFi™ Demo & Recording Playbook

A complete guide and automated runner to create high-converting, viral video demos of **VoiceFi** for **Twitter/X, Product Hunt, YouTube, and Show HN**.

---

## ⚡ 1-Click Automated Demo Runner

We built a dedicated demo stage runner that presents the features in terminal with live audio cues, neural agent voices, and diagrams:

```bash
# 🎯 Option A: Interactive Mode (Press Enter to advance scene by scene as you speak)
uv run python scripts/run_live_demo.py

# ⏱️ Option B: Fully Automated 45-Second Timed Recording Mode
uv run python scripts/run_live_demo.py --auto
```

---

## 🎬 Video Script 1: The 30-Second Viral Teaser (For X / Twitter / LinkedIn)

> **Goal:** Hook developer attention in 3 seconds, show the magic of hands-free agent control, and drop the open-source link.

| Timestamp | Visual (Screen) | Spoken Audio / Narration |
| :--- | :--- | :--- |
| **0:00 - 0:06** | Split screen: Antigravity/Claude terminal on the left running tests. You lean back or hold a coffee cup. | *"What if you never had to switch terminal tabs or babysit your AI coding agents again?"* |
| **0:06 - 0:14** | Agent finishes turn $\rightarrow$ VoiceFi HUD pops up $\rightarrow$ Speaker plays Christopher's voice: *"Refactored SQLite pool. All tests are green."* | VoiceFi speaks aloud: *"Refactored SQLite connection pool. All 42 tests passed. Ready to commit?"* |
| **0:14 - 0:22** | Mic opens automatically with chime $\rightarrow$ You speak naturally: *"Looks clean, commit and push to main."* $\rightarrow$ Transcribes instantly and injects into terminal. | You speak hands-free. Local Whisper transcribes in 120ms without touching the keyboard. |
| **0:22 - 0:30** | Terminal shows `curl -fsSL https://vifi.sh \| bash` + GitHub stars badge. | *"VoiceFi: 100% open source, local Whisper on Apple Silicon, and zero subscriptions. Link in bio."* |

---

## 🎬 Video Script 2: The 90-Second Product Walkthrough (For Product Hunt / YouTube / Website Hero)

### 📌 Act 1: The Problem & 1-Line Setup (0:00 - 0:20)
* **Visual:** Open clean dark-mode terminal.
* **Narration:** *"AI coding agents like Claude Code, Antigravity, and Cursor are incredible—but you spend half your day tab-switching and babysitting progress bars. Meet VoiceFi: the universal voice layer for macOS and AI agents."*
* **Action:** Run `curl -fsSL https://vifi.sh | bash` followed by `vifi setup`.

### 📌 Act 2: Distinct Acoustic Personas for Agents (0:20 - 0:40)
* **Visual:** Terminal running `vg voice audition` and `vg voice set`.
* **Narration:** *"VoiceFi gives every agent in your swarm an acoustic identity. Your main planner, researcher, and QA debugger each get distinct neural voices."*
* **Action:** Run `uv run python scripts/demo_multi_agent_flow.py` and let Christopher, Sonia, and Aria speak their status updates sequentially.

### 📌 Act 3: Hands-Free Ambient Feedback Loop (0:40 - 1:05)
* **Visual:** Agent finishes a complex code refactor in Antigravity or Claude Code.
* **Narration:** *"When your agent finishes a task or asks a question, VoiceFi speaks a brief soundbite, chimes, and auto-listens for your response. You can reply from across the room."*
* **Action:** Demonstrate voice response being injected directly into the active terminal session.

### 📌 Act 4: The Voice Memo Buffer (1:05 - 1:25)
* **Visual:** Run `vg memo record -d 2m` or `vg memo synth`.
* **Narration:** *"Have a stream of consciousness idea while pacing? Hit record and talk. VoiceFi synthesizes your unstructured ramble into an architecture diagram, implementation plan, and PR checklist."*
* **Action:** Terminal prints formatted Mermaid chart and checklist.

### 📌 Act 5: Call to Action (1:25 - 1:35)
* **Visual:** VoiceFi website ([voicefi.org](https://voicefi.org)) and GitHub repository.
* **Narration:** *"VoiceFi is 100% MIT open source and runs entirely on device. Try it today with `vifi setup`."*

---

## 📹 Screen Recording Setup Checklist

To ensure your demo looks and sounds studio-grade:

1. **Resolution & Aspect Ratio:**
   - **X / Social Clips:** 1920x1080 (16:9) or 1080x1080 (1:1).
   - **Product Hunt Video:** 1920x1080 HD (YouTube/Vimeo embed or MP4).
2. **Terminal Appearance:**
   - **Font:** JetBrains Mono or SF Mono, size **18–20pt** (high legibility on mobile).
   - **Theme:** Dark mode (e.g. Catppuccin Mocha, Tokyo Night, or Apple Dark).
   - **Window Size:** Compact, centered on screen, padding around edges.
3. **Audio Routing:**
   - Record **System Audio** (so VoiceFi TTS neural voices & chimes are crystal clear).
   - Record **Microphone Audio** (for your natural voice responses).
   - *Tools:* CleanShot X, OBS Studio, Loom, or ScreenFlow.

---

## 📱 Social Post Copy Templates

### 🐦 Tweet / Post Copy (For Launch Video):
```
I got tired of babysitting terminal tabs and waiting for AI agents to finish coding.

So I built VoiceFi: the Universal Voice Layer for AI Agents, MCP, and macOS.

✨ Agent finishes work ➔ speaks aloud
🎙️ Auto-opens mic with VAD (hands-free)
🧠 Local Whisper on Apple Silicon (offline)
🎭 Signature voice personas for subagents
📝 Pacing voice memos ➔ instant PR plans

100% Free & Open Source (MIT) 🚀

⚡ Quick install:
curl -fsSL https://vifi.sh | bash

Repo: https://github.com/atxatlarge-code/voicefi
Site: https://voicefi.org
```

### 🐱 Product Hunt Tagline & First Comment:
* **Tagline:** Universal voice layer for AI coding agents & macOS
* **Maker Comment:**
> *"Hey everyone! We built VoiceFi because AI coding agents (Claude Code, Antigravity, Cursor) run autonomously in the background, but communicating with them still felt stuck in 1995 terminal prompts. VoiceFi bridges the gap with an ambient voice loop—so your agents tell you when they're done, listen for your voice instructions hands-free, and let you pace while brain-dumping plans directly into code. 100% MIT Open Source, local Whisper powered."*


