# Agent Execution Efficiency & Context Guardrails

To prevent runaway conversation turns and catastrophic context/token bloat (which can burn tens of millions of tokens in a single session), all AI agents operating in this workspace must strictly adhere to the following execution constraints:

## 1. Zero-Polling on Background Tasks
- **NEVER poll `manage_task(Action='status')` in a loop.** The runtime environment automatically wakes the agent with a reactive notification when any background task completes.
- **Set `WaitMsBeforeAsync: 10000`**: For any command expected to terminate within 10 seconds (e.g. `pytest`, `vifi voice test`, server reloads, fast builds), set `WaitMsBeforeAsync: 10000` so execution completes synchronously and never transitions to a background task unnecessarily.
- If a task is sent to the background, **stop calling tools immediately** and wait for the system completion message.

## 2. Large-File Context Guard (>300 Lines)
- **NEVER call `view_file` without line bounds on files over 300 lines** (e.g. `antigravity.py`, `tray.py`, `server.py`, `voice_acting.py`).
- For any file >300 lines, the agent **MUST** either:
  1. Use `voicefi_scout` (or `vifi scout <file> -q "<query>"`): Reads the file in Apple Silicon unified memory in <0.2ms and returns a ~150-token semantic slice.
  2. Use `view_file` with explicit `StartLine` and `EndLine` (maximum 100-line slice).
- Ingesting entire 1,000+ line files directly into the cloud conversation context is strictly forbidden.
- **Do NOT use chained bash commands (`sed -n`, `head`, `tail`, `grep`) to read source code chunks.**

## 3. The 3-Step Subagent Delegation Rule
- If an investigation, diagnostic triage, or test failure resolution requires **more than 3 consecutive exploratory tool calls** without a conclusive fix, the agent **MUST delegate** the task to an isolated subagent (`invoke_subagent` with `research` or `self`).
- **Why**: Deep debugging spikes in the main conversation thread permanently bloat the session context. In late-stage conversations (100k+ tokens), every single micro-action re-ingests the entire history.
- The subagent runs its trial-and-error cycle in an isolated transcript and returns only a concise root-cause summary and targeted patch.

## 4. VoiceFi Programmatic Verification
- When verifying voices, TTS latency, or audio pipelines, **use the structured CLI**:
  ```bash
  vifi voice test <voice_name> --json
  ```
- Avoid writing ad-hoc inline Python scripts (`python -c "..."`) or manually parsing process tables (`ps aux | grep ...`).
- When transitioning from code refactoring to interactive subjective voice auditioning with the user, suggest a fresh thread or use the dedicated testing scripts to keep the development thread lean.

## 5. Local-QA Test & Linter Gatekeeper
- **Do NOT run repetitive `pytest` loops in the cloud chat context.** (Running 10-60 pytest runs in cloud conversation burns massive tokens and degrades context).
- For test verification and linting, invoke the local on-device verification runner:
  ```bash
  uv run python scripts/local_qa.py --test-target <optional_test_path>
  ```
  or pipe failing tests into `vifi fix`:
  ```bash
  pytest <test_file> | vifi fix
  ```
- The local model (`qwen2.5-coder` or `gemma4-2b`) resolves syntax regressions locally on Metal GPU up to 3 turns and outputs only a concise scorecard to `.agents/QA_AUDIT.md`. Cloud context ingests only the clean unified git diff.
