# 🗺️ VoiceFi Product & Intelligence Roadmap

---

## 🚨 High Priority (Next Up)

### 1. Acoustic Turn Handoff & HUD "Next Up" Pill
* **Objective**: Connect turn completion and lifecycle hooks (`vifi hook`) to pipeline state awareness.
* **Spoken Audio Specification**:
  * If a multi-phase task is active and has a pending next step, the agent's turn-end speech delivers:
    * **Sentence 1**: What was completed in this turn (e.g., *"Unit tests passed and circular buffer is staged."*)
    * **Sentence 2**: What is next up (e.g., *"Next step is Phase 2: connect buffer to WebRTC peer connection."*)
* **Visual HUD / Menu Bar Pill**:
  * Pushes active step title into the VoiceFi Unified HUD and macOS menu bar tray pill.
  * Clicking the pill or pressing `⌥V` (Option+V) copies/pastes the exact resume prompt.
* **On-Device Verification**:
  * Uses local Gemma on Apple Silicon Metal GPU (`LocalModelEngine` / LiteRT) to verify the turn handoff state in <50ms with zero cloud tokens.

---

## 📌 Active & Backlog Initiatives

### 2. Multi-Agent Cross-Bridge Protocol
* Antigravity and Claude Code continuous IPC session synchronization.
* Shared task handoffs across terminal CLI and GUI editor surfaces.

### 3. VoiceFi Ambient Standup & Real-Time Note Taker
* Real-time extraction of architectural decisions and action items directly into markdown journals.
