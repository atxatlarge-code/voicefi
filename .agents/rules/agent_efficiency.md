# Agent Execution Efficiency & Context Guardrails

To prevent runaway conversation turns and catastrophic context/token bloat (which can burn tens of millions of tokens in a single session), all AI agents operating in this workspace must strictly adhere to the following execution constraints:

## 1. Zero-Polling on Background Tasks
- **NEVER poll `manage_task(Action='status')` in a loop.** The runtime environment automatically wakes the agent with a reactive notification when any background task completes.
- **Set `WaitMsBeforeAsync: 10000`**: For any command expected to terminate within 10 seconds (e.g. `pytest`, `vifi voice test`, server reloads, fast builds), set `WaitMsBeforeAsync: 10000` so execution completes synchronously and never transitions to a background task unnecessarily.
- If a task is sent to the background, **stop calling tools immediately** and wait for the system completion message.

## 2. Mandatory On-Device Local-Scout Gatekeeper
- **NEVER read raw log files into cloud context.** For any log file (`/tmp/*.log`, `/tmp/*.err`, `/var/log/*`, `transcript.jsonl`, or crash reports), the agent **MUST** run the on-device recon scout:
  ```bash
  uv run python -m voicefi.local.scout <log_path> -q "<question/objective>"
  ```
  This executes in Apple Silicon unified memory in <0.2ms, saving 85%+ context overhead and returning only a ~150-token distilled signal.
- **NEVER repeatedly slice large source files (>300 lines)** with `view_file` or chained bash commands (`sed -n`, `head`, `tail`, `grep`). If the line numbers of the target logic are unknown:
  1. First run `uv run python -m voicefi.local.scout <file_path> -q "<query>"` to locate the exact functions and line numbers.
  2. Only call `view_file` once on the precise 20-50 line slice identified by the scout.

## 3. Mandatory Hardware & Memory Telemetry Gate
- **NEVER write ad-hoc inline Python scripts (`python -c "import psutil..."`) or manually parse `ps aux` / `vm_stat` tables.**
- When checking system RAM, thermal throttling, or model load safety, **ALWAYS invoke `ThermalSupervisor` directly**:
  ```bash
  uv run python -m voicefi.local.supervisor
  ```
  This immediately reports thermal pressure, available unified RAM, active disk swap, and model clearance (Gemma, Qwen, Llama 70B) in a single structured output.

## 4. Mandatory On-Device Surgical Implementation (`local-dev`)
- For single-parameter config modifications, localized AST refactors, or bug remedies, prioritize the on-device engineer:
  ```bash
  vifi implement <file_path> -i "<instruction>"
  ```
  or pipe failing test traces directly:
  ```bash
  pytest <test_file> | vifi fix
  ```
  Cloud context ingests only the resulting unified git diff, eliminating cloud file rewriting costs.

## 5. The 3-Step Subagent Delegation Rule
- If an investigation, diagnostic triage, or test failure resolution requires **more than 3 consecutive exploratory tool calls** without a conclusive fix, the agent **MUST delegate** the task to an isolated subagent (`invoke_subagent` with `research` or `self`).
- **Why**: Deep debugging spikes in the main conversation thread permanently bloat the session context. In late-stage conversations (100k+ tokens), every single micro-action re-ingests the entire history.
- The subagent runs its trial-and-error cycle in an isolated transcript and returns only a concise root-cause summary and targeted patch.

## 6. VoiceFi Programmatic Verification
- When verifying voices, TTS latency, or audio pipelines, **use the structured CLI**:
  ```bash
  vifi voice test <voice_name> --json
  ```
- When transitioning from code refactoring to interactive subjective voice auditioning with the user, suggest a fresh thread or use the dedicated testing scripts to keep the development thread lean.
