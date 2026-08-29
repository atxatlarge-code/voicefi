---
name: cross-agent-bridge
description: Enables Antigravity and Claude Code to communicate seamlessly, delegate tasks, exchange findings, play corny joke sound effects (drum smash, honks, applauses), and engage in multi-turn spoken voice dialogue using VoiceFi using targeted Conversation IDs as the primary default.
---

# 🌉 Cross-Agent Bridge Skill (Antigravity ↔ Claude Code)

Use this skill whenever:
- You need to send a task, question, or finding to **Claude Code** (if you are Antigravity) or to **Antigravity** (if you are Claude Code).
- You want tools to communicate cleanly by Conversation ID so messages appear in the UI without screen flicker or window focus stealing.
- You are participating in a multi-agent dialogue, joke duel, or cooperative pair-programming session.
- You want to play comedic sound effects (`drum_smash`, `honk`, `sad_trombone`, `applause`) during jokes and banter.

---

## 🎯 Default Standard: Conversation ID Routing (Visible in UI, 0 Screen Flash)

By default, all tool-to-tool and agent-to-agent communication should route through **Conversation IDs**:
- **Appears in UI**: The full message, title, and attribution render directly in the conversation history.
- **Zero Focus Change / Zero Flash**: Delivered through native background socket APIs without stealing window focus, pasting over user clipboards, or popping windows.

### 1. Replying to Originating Conversation
When returning findings or answering a delegated task:

```bash
vifi send "Refactoring complete! All 14 tests passing." --to antigravity --reply
```

### 2. Targeting a Specific Conversation ID
To target any specific conversation or subagent thread by its UUID:

```bash
vifi send "Security audit findings for PR #42" \
  --to antigravity \
  --id <CONVERSATION_ID> \
  --title "Security Audit" \
  --sender "Claude"
```

Or via REST API:
```bash
curl -s -X POST http://localhost:5141/api/send \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Security audit findings",
    "engine": "antigravity",
    "conv_id": "<CONVERSATION_ID>",
    "title": "Security Audit",
    "sender_name": "Claude"
  }'
```

---

## 🚀 Other Available Dispatch Modes

### Mode 2: Foreground Window Injection (Interactive Claude Terminal / App)
*Use only when you specifically want to bring Claude Code to the front on screen and submit directly into the interactive prompt.*

```bash
vifi send "Review the changes in src/voicefi/audio/sfx.py" --to claude
```

### Mode 3: Spawn a Brand New Conversation (Focus in UI)
*Spawns a fresh conversation workspace, sets the title, creates the chat tab, and focuses the UI window.*

```bash
vifi new "Refactor auth middleware and implement OAuth2 PKCE" --title "Auth Refactor"
```

---

## 🥁 Corny Joke Sound Effects & Comedy Cues

| Sound Effect | Trigger Command | Comedy Purpose |
| :--- | :--- | :--- |
| **Drum Smash (Ba-dum-tss! 🥁)** | `vifi sfx drum_smash` (or `vifi sfx drums`) | Classic comedy drum smash + cymbal crash after a punchline |
| **Horn Honk (📯 / 🚗)** | `vifi sfx honk` | Corny clown horn / double cab beep |
| **Sad Trombone (🎺)** | `vifi sfx sad_trombone` | Comedic disappointment / groan (wah-wah-wah-waaaah) |
| **Applause / Cheer (👏 / 🎉)** | `vifi sfx applause` | Crowd clapping & cheering for the grand finale |
| **Boing (🌀)** | `vifi sfx boing` | Cartoon spring bounce |
| **Crickets (🦗)** | `vifi sfx crickets` | Awkward silence / deadpan pause |

### Inline Sound Tags in Spoken Text
```text
"The bar bursts into flames! [sfx:drum_smash]"
"None, that's a hardware problem! [sfx:applause]"
```

---

## 🎙️ Spoken Voice Personas
- **Antigravity**: *Ava / Viv* persona (`en-US-AvaNeural`) — sharp, modern, expressive.
- **Claude Code**: *Steffan / Guy* persona (`en-US-SteffanNeural`) — warm, conversational pair-programmer.
