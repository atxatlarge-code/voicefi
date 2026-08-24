# 📐 VoiceFi™ Architecture: The Universal MCP Voice Layer
> **Model Context Protocol (MCP) Server & Client Integration Specification**  
> **Target:** VoiceFi Core Daemon, CLI, & Multi-Agent Orchestration  
> **Patent Reference:** U.S. Patent Application No. 63/137,300 (*LienLogic Data LLC*)

---

## 1. Executive Summary

As AI coding assistants and autonomous multi-agent systems (**Antigravity, Claude Code, Cursor, Windsurf**) transition to the **Model Context Protocol (MCP)** standard, VoiceFi has a unique opportunity to become the **Universal Voice & Ambient Audio Layer** for the entire AI ecosystem.

This document specifies the bidirectional MCP architecture for VoiceFi:
1. **VoiceFi as an MCP Server (`voicefi-mcp`)**: Exposes native audio synthesis, active listening, hands-free confirmation prompts, and acoustic voice personas as standard MCP tools to any external AI agent.
2. **VoiceFi as an MCP Client / Voice-Dispatcher**: Translates ambient spoken voice commands into structured tool executions across external MCP servers (e.g., Slack, Linear, GitHub, Postgres, DevTools).

```
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                      EXTERNAL AGENTS & IDEs                                │
 │               (Antigravity, Claude Code, Cursor, Zed)                       │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │ stdio / SSE (MCP Tools & Prompts)
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                       VOICEFI AS AN MCP SERVER                              │
 │  • voicefi_speak(text, persona, priority)                                   │
 │  • voicefi_ask_confirmation(prompt, timeout)                                │
 │  • voicefi_get_ambient_context()                                            │
 │  • voicefi_set_agent_persona(agent_id, persona)                             │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                      VOICEFI CORE AUDIO DAEMON                              │
 │  [Streaming STT (Whisper/Groq)] ◄──► [TTS Personas] ◄──► [Energy VAD Engine]│
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
                                        ▼ (Dispatched Voice Actions)
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                       EXTERNAL MCP TOOL CLIENTS                             │
 │  ┌─────────────────┐    ┌──────────────────┐    ┌────────────────────────┐  │
 │  │    Slack MCP    │    │    Linear MCP    │    │  Postgres / DB MCP     │  │
 │  │ (Channels, DMs) │    │  (Issues, Sync)  │    │  (Staging / Schemas)   │  │
 │  └─────────────────┘    └──────────────────┘    └────────────────────────┘  │
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. VoiceFi as an MCP Server (`voicefi-mcp`)

By implementing an MCP server, any AI agent on macOS can connect to VoiceFi with zero custom plugin installations.

### 2.1 Server Capabilities & Primitives

#### `voicefi_speak`
Allows any agent to synthesize and speak audio through macOS system output or connected AirPods.
* **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "text": { "type": "string", "description": "The message to speak aloud (pre-summarized)." },
      "persona": { "type": "string", "enum": ["christopher", "sonia", "guy", "aria"], "default": "christopher" },
      "priority": { "type": "string", "enum": ["low", "normal", "urgent"], "default": "normal" },
      "interrupt_current": { "type": "boolean", "default": false }
    },
    "required": ["text"]
  }
  ```
* **Use Case:** Background build alerts, long-running migration finishes, PR review completed.

#### `voicefi_ask_confirmation`
Allows an agent to pause execution, speak a question to the user, activate the microphone with Voice Activity Detection (VAD), and return the verbal response.
* **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "question": { "type": "string", "description": "Spoken question to ask the user." },
      "timeout_seconds": { "type": "integer", "default": 15 },
      "expected_responses": { "type": "array", "items": { "type": "string" }, "description": "e.g. ['yes', 'proceed', 'cancel']" }
    },
    "required": ["question"]
  }
  ```
* **Use Case:** Destructive database migrations, production deployments, git pushes.

#### `voicefi_get_ambient_context`
Returns the recent transcription buffer of ambient voice memos, pacing thoughts, or meetings.
* **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "since_minutes": { "type": "integer", "default": 10 }
    }
  }
  ```

---

## 3. Dedicated Spoken Workflows: The VoiceFi + Slack MCP Blueprint

The integration between VoiceFi’s speech engine and the Slack MCP server eliminates manual typing, channel hunting, and message formatting.

### 3.1 Workflow Architecture: Spoken Voice ➔ Polished Slack Action

```
[User Speaks into VoiceFi Mic / Hotkey]
       │
       ▼
[Streaming Whisper STT: Fast Transcription]
       │
       ▼
[Intent & Entity Classifier]
   ├── Target: User (@alex) or Channel (#dev, #incidents)
   ├── Action: Post Message, Reply to Thread, or Summarize Channel
   └── Raw Transcript (with filler words)
       │
       ▼
[Conversational Cleanup & Slack Markdown Formatter]
   ├── Strips: "um", "uh", repetitions
   └── Enriches: Code blocks, bulleted lists, bold highlights
       │
       ▼
[Auditory Safety Gate (Optional)]
   └── VoiceFi: "Ready to post standup to #engineering. Send it?"
       └── User: "Yes"
       │
       ▼
[Slack MCP Execution: slack_post_message / slack_reply_to_thread]
       │
       ▼
[Spoken Audio Feedback: "Message posted to #engineering."]
```

### 3.2 Core Slack Voice Scenarios

#### Scenario A: The Pacing Morning Standup
1. **User Speaks:** *"VoiceFi, post standup to engineering: yesterday merged PR 104 and fixed audio buffer overflow, today implementing the MCP server spec, no blockers."*
2. **Engine Output:** Calls `slack_post_message` with:
   ```markdown
   *Daily Standup — @Jake*
   • *Yesterday:* Merged PR #104 (audio buffer overflow fix)
   • *Today:* Implementing MCP server specification
   • *Blockers:* None
   ```
3. **Feedback:** Instant audio chime + *"Posted standup to #engineering."*

#### Scenario B: Thread Summary & Audio Reply
1. **User Speaks:** *"Catch me up on the recent thread in #incidents."*
2. **MCP Action:** Calls `slack_get_channel_history` and `slack_get_thread_replies`.
3. **VoiceFi Speaks:** *"Dave flagged a 500 error on the Stripe checkout webhook 6 minutes ago. Maria is checking logs."*
4. **User Speaks:** *"Reply to Dave that I'm deploying the webhook hotfix now."*
5. **MCP Action:** Calls `slack_reply_to_thread(thread_ts=..., message="Deploying webhook hotfix now.")`.

#### Scenario C: Thought-to-DM Dispatch
1. **User Speaks:** *"Shoot a DM to Sarah: looked at the latency logs for Groq STT, we're hitting 160ms average which is well within our budget, let's proceed with the rollout."*
2. **MCP Action:** Resolves user ID via `slack_get_users` -> formats crisp DM -> sends message.

---

## 4. Multi-Agent Voice Persona System

When orchestrating multi-agent teams (e.g. within Antigravity or Claude Code), each subagent is assigned a distinct neural acoustic persona via `voicefi-mcp`:

| Agent Role | Voice Persona | Tone & Characteristics | Primary Notification Types |
| :--- | :--- | :--- | :--- |
| **Architect / Lead** | **Christopher** | Warm, authoritative, deep | Architecture decisions, phase completions |
| **QA / Test Engineer** | **Aria** | Energetic, crisp, precise | Unit test failures, lint errors, edge cases |
| **Data / Research** | **Sonia** | Analytical, clear, calm | RAG search results, database query answers |
| **DevOps / Release** | **Guy** | Direct, fast, pragmatic | Build statuses, container health, deployments |

---

## 5. Strategic Benefits for VoiceFi

1. **Ecosystem Interoperability**: VoiceFi becomes instantly compatible with any MCP client (Claude Desktop, Antigravity, Cursor, Windsurf, OpenDevin).
2. **Zero Maintenance for New Apps**: As new developer tools publish MCP servers (e.g., Supabase, Figma, Jira), VoiceFi automatically gains voice control over them without writing new custom integrations.
3. **Expansion from Dictation to Ambient OS**: Positions VoiceFi not merely as a typing replacement, but as the **auditory interface of desktop computing**.

---

## 6. Implementation Roadmap

- [ ] **Phase 3.1: Core `voicefi-mcp` Server Implementation**
  - Implement FastMCP / Stdio server transport.
  - Expose `voicefi_speak`, `voicefi_ask_confirmation`, and `voicefi_status`.
- [ ] **Phase 3.2: VoiceFi Intent-to-MCP Dispatcher**
  - Connect VoiceFi STT stream directly to local MCP client registry.
  - Natural language parser for tool argument generation.
- [ ] **Phase 3.3: Slack Voice Suite**
  - Out-of-the-box templates for Standups, DMs, Thread Summaries, and Audio Notifications.
- [ ] **Phase 3.4: Multi-Persona Subagent Audio Router**
  - Dynamic voice persona switching based on calling subagent ID.
