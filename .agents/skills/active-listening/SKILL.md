---
name: active-listening
description: Enhances AI agents with active listening, intent verification, acoustic cognitive safety, and phonetic spoken-code normalization.
---

# 👂 Active Listening & Cognitive Safety Skill

Use this skill when receiving spoken developer instructions, audio dictation, or ambient meeting context. It ensures that the agent actively verifies understanding, resolves phonetic ambiguities, and safeguards against destructive operations before execution.

---

## 🎯 Core Objectives

1. **Paraphrase Destructive Actions**: Before executing dangerous operations (e.g. `rm -rf`, `DROP TABLE`, `git reset --hard`, deleting branches), speak or summarize the exact interpretation back to the user:
   > *"I heard: delete the migrations folder and recreate the schema. Should I proceed?"*
2. **Contextual Disambiguation**: If an utterance is clipped, noisy, or ambiguous, ask a single, crisp clarifying question rather than guessing.
3. **Phonetic Normalization**: Recognize and normalize spoken developer slang into precise syntax (e.g. *"pie test"* -> `pytest`, *"cube cuddle"* -> `kubectl`, *"camel case"* -> `camelCase`).
4. **Active Reflection**: Acknowledge completed multi-step audio instructions with concise, structured milestones.

---

## 🛠️ Spoken Shorthand & Phonetic Mapping

When processing spoken instructions, always map colloquial developer speech to actual commands and syntax:

| Spoken Phrase | Normalized Syntax | Example Spoken Input | Resulting Command / Code |
| :--- | :--- | :--- | :--- |
| *"pie test"* / *"pie test dash v"* | `pytest -v` | *"run pie test on test auth"* | `pytest tests/test_auth.py -v` |
| *"cube cuddle"* / *"cube control"* | `kubectl` | *"cube cuddle get pods"* | `kubectl get pods` |
| *"git checkout dash b"* | `git checkout -b` | *"git checkout dash b feature stripe"* | `git checkout -b feature/stripe` |
| *"git push origin main"* | `git push origin main` | *"push to origin main"* | `git push origin main` |
| *"camel case"* | `camelCase` | *"variable user id in camel case"* | `userId` |
| *"snake case"* | `snake_case` | *"function get user info in snake case"* | `get_user_info()` |
| *"kebab case"* | `kebab-case` | *"file name payment flow in kebab case"* | `payment-flow.tsx` |
| *"dock er compose up"* | `docker compose up` | *"run dock er compose up in background"* | `docker compose up -d` |

---

## 🚦 The 3-Tier Verification Protocol

### Tier 1: Low Risk (Instant Execution)
- **Actions**: Reading files, running tests, querying logs, searching the web, checking git status.
- **Behavior**: Execute immediately without asking. Provide a brief soundbite when finished.

### Tier 2: Medium Risk (Speculative / Ambiguous)
- **Actions**: Drafting a new component, scaffolding a route, researching a complex architectural decision.
- **Behavior**: If in ambient mode, spawn an isolated subagent in `Workspace="branch"`. If direct, execute and summarize changes concisely.

### Tier 3: High Risk (Destructive / Irreversible)
- **Actions**: Deleting files/tables, resetting git history, pushing directly to production/main, terminating background daemons.
- **Behavior**: **Mandatory Confirmation**. Paraphrase what was heard and wait for explicit verbal or written approval.

---

## 💡 Example Active Listening Scenarios

### Scenario A: Destructive Command Spoken
- **User says**: *"Wipe the staging database and drop the old user sessions."*
- **Agent response**:
  > ⚠️ *"I heard: wipe the staging database and drop table `user_sessions`. This will permanently remove session records. Please confirm before I execute."*

### Scenario B: Speculative Idea during Meeting
- **User says**: *"Maybe we should look into WebSockets for real-time order sync."*
- **Agent reaction**:
  - Automatically launches a background `research` subagent.
  - Pre-fetches the current API architecture and compares WebSockets vs Server-Sent Events (SSE).
  - Prepares notes for when the user is ready.
