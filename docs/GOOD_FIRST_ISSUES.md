# 🎯 VoiceFi™ Good First Issues Catalog
> **Curated, Actionable Starter Issues for Open-Source Contributors**  
> *Ready for Community Hackers, AI Tool Builders, and Voice Enthusiasts*

Welcome to the VoiceFi contributor community! Whether you are a Python developer, an audio engineering enthusiast, or an AI agent hacker, these curated issues are designed to help you make your first meaningful open-source contribution to VoiceFi.

Each issue includes clear problem definitions, pointers to exact codebase files, step-by-step implementation guidance, and concrete acceptance criteria.

---

## 📋 Quick Issue Navigation Matrix

| # | Issue Title | Area | Difficulty | Est. Time | Key Files |
|---|---|---|---|---|---|
| [1](#issue-1-add-kokoro-82m-offline-neural-tts-provider-for-linux--windows) | **Add Kokoro 82M Offline Neural TTS Provider** | `TTS` `OS` | `Medium` | 3–5 hrs | `src/voicefi/tts/kokoro.py`<br>`src/voicefi/tts/catalog.py` |
| [2](#issue-2-add---json-output-flag-to-all-diagnostic-cli-commands) | **Add `--json` Output Flag to Diagnostic CLI Commands** | `CLI` `MCP` | `Easy` | 1–2 hrs | `src/voicefi/cli.py`<br>`src/voicefi/troubleshoot.py` |
| [3](#issue-3-auto-config-generator-for-cursor--zed-in-vifi-setup) | **Auto-Config Generator for Cursor & Zed in `vifi setup`** | `CLI` `IDE` | `Easy` | 2–3 hrs | `src/voicefi/cli.py`<br>`src/voicefi/integrations/discovery.py` |
| [4](#issue-4-directory-based-custom-sound-effect-pack-loader) | **Directory-Based Custom Sound Effect Pack Loader** | `SFX` `Audio` | `Easy` | 2–3 hrs | `src/voicefi/audio/sfx.py`<br>`src/voicefi/cli.py` |
| [5](#issue-5-cross-platform-native-desktop-notification-fallback) | **Cross-Platform Native Desktop Notification Fallback** | `OS` `UI` | `Easy` | 1–2 hrs | `src/voicefi/ui/notifications.py` |
| [6](#issue-6-rich-terminal-audio-waveform-meter-for-vifi-listen) | **Rich Terminal Audio Waveform Meter for `vifi listen`** | `CLI` `Audio` | `Easy` | 1–2 hrs | `src/voicefi/audio/recorder.py`<br>`src/voicefi/cli.py` |

---

## 🛠️ Issue 1: Add Kokoro 82M Offline Neural TTS Provider for Linux & Windows

- **Difficulty**: 🟡 Medium (`Good First Engine Issue`)
- **Area**: `TTS`, `OS`, `Neural Audio`
- **Labels**: `good first issue`, `enhancement`, `cross-platform`, `tts`
- **Target Release**: Phase 2

### 1. Description
While macOS users enjoy Apple's instant neural `Ava (Premium)` voice for 0ms offline speech synthesis, Linux and Windows contributors currently fall back to classic system voices or cloud EdgeTTS. 

**Kokoro 82M** is a state-of-the-art, lightweight (82M parameter) neural text-to-speech model that runs entirely on-device via ONNX runtime with sub-200ms latency on modern CPUs. Adding native Kokoro support gives Linux and Windows developers an instant, private, offline neural voice experience.

### 2. Relevant Codebase Files
- `src/voicefi/tts/base.py`: Abstract base class `BaseTTS` and cross-process speech lock interfaces.
- `src/voicefi/tts/kokoro.py` *(New File)*: Concrete implementation of `KokoroTTS`.
- `src/voicefi/tts/catalog.py`: Add Kokoro voice personas (`kokoro-af-sarah`, `kokoro-am-michael`).
- `src/voicefi/tts/__init__.py`: Register `kokoro` in `get_tts_engine()`.
- `tests/test_kokoro_tts.py` *(New File)*: Unit and integration tests.

### 3. Step-by-Step Implementation Guidance
1. **Create `src/voicefi/tts/kokoro.py`**:
   - Subclass `BaseTTS`.
   - Implement lazy initialization: check if `kokoro-onnx` is installed; if not, raise an informative error instructing the user (`pip install kokoro-onnx soundfile`).
   - Store downloaded ONNX model weights in `~/.voicefi/models/kokoro/`.
2. **Implement Synthesis & Audio Playback**:
   - In `synthesize(text, voice, ...)`: convert text to phonemes and run ONNX model inference to produce a NumPy float32 array at 24kHz.
   - Use `soundfile.write` or `sounddevice.play` respecting `self._audio_player`.
   - Wrap playback with `_acquire_speech_lock()` and `set_cross_process_agent_speaking()` from `src/voicefi/tts/base.py` to ensure proper VAD acoustic safe-mode synchronization.
3. **Update Catalog & Engine Factory**:
   - In `src/voicefi/tts/catalog.py`, append `VoicePersona(id="kokoro-sarah", name="Sarah (Kokoro)", provider="kokoro", ...)` to `CURATED_PERSONAS`.
   - In `src/voicefi/tts/__init__.py`, add `"kokoro": KokoroTTS` to the engine dispatch dictionary.

### 4. Acceptance Criteria
- [ ] Running `vifi voice set antigravity kokoro-sarah` successfully saves configuration.
- [ ] Running `vifi voice test kokoro-sarah -t "Hello from Kokoro offline voice."` speaks audio without internet access.
- [ ] Graceful fallback: If ONNX model files are missing, `vifi` provides clear download instructions or auto-downloads from HuggingFace.
- [ ] Unit tests in `tests/test_kokoro_tts.py` pass cleanly with mocked ONNX inference.

---

## 📊 Issue 2: Add `--json` Output Flag to all Diagnostic CLI Commands

- **Difficulty**: 🟢 Easy (`Starter Issue`)
- **Area**: `CLI`, `MCP`, `Automation`
- **Labels**: `good first issue`, `dx`, `cli`, `json`
- **Target Release**: Phase 1.5

### 1. Description
AI coding agents (Antigravity, Claude Code), external shell scripts, and CI runners frequently invoke `vifi` CLI commands to inspect system state. While commands like `vifi troubleshoot --json` produce structured output, commands such as `vifi status`, `vifi ping`, and `vifi stats` print formatted ANSI tables that are difficult to parse programmatically.

Adding a `--json` / `-j` flag to all diagnostic commands enables machine-readable introspection across all developer environments.

### 2. Relevant Codebase Files
- `src/voicefi/cli.py`:
  - `cmd_server(args)` / `cmd_status(args)`
  - `cmd_ping(args)`
  - `cmd_stats(args)`
- `src/voicefi/troubleshoot.py`: Diagnostic helper methods.
- `tests/test_cli_layout.py`: CLI output testing.

### 3. Step-by-Step Implementation Guidance
1. **Add CLI Parser Arguments**:
   - In `src/voicefi/cli.py`, add `-j` / `--json` arguments to `status_parser`, `ping_parser`, and `stats_parser`:
     ```python
     parser.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON")
     ```
2. **Implement Structured Dictionary Return**:
   - In `cmd_server()` / `cmd_status()`:
     ```python
     if getattr(args, "json", False):
         status_payload = {
             "status": "online" if is_running else "stopped",
             "port": 5141,
             "pid": pid,
             "launchagent_loaded": is_launchagent_active(),
             "active_voice": config.voice.antigravity,
             "barge_in_mode": config.vad.barge_in,
         }
         print(json.dumps(status_payload, indent=2))
         return
     ```
   - In `cmd_ping()`: return `{ "voice": voice, "ttfb_ms": ttfb, "throughput_cps": cps, "status": "ok" }`.
   - In `cmd_stats()`: return `{ "turns_total": turns, "time_saved_sec": saved, "tools": tool_counts }`.
3. **Sanitize ANSI Codes**: Ensure no rich color formatting or emojis are printed when `--json` is enabled.

### 4. Acceptance Criteria
- [ ] `vifi status --json | jq .status` outputs `"online"` or `"stopped"`.
- [ ] `vifi ping --json | jq .ttfb_ms` parses as a valid float.
- [ ] `vifi stats --json | jq .` returns valid JSON with exit code 0.
- [ ] Existing non-JSON human-readable output is completely preserved when `--json` is omitted.

---

<a id="issue-3-auto-config-generator-for-cursor-cursormcpjson-and-zed-settingsjson-in-vifi-setup"></a>
## ⚡ Issue 3: Auto-Config Generator for Cursor & Zed in `vifi setup`

- **Difficulty**: 🟢 Easy (`Starter Issue`)
- **Area**: `CLI`, `IDE`, `MCP`
- **Labels**: `good first issue`, `dx`, `cursor`, `zed`, `mcp`
- **Target Release**: Phase 2

### 1. Description
`vifi setup` automatically registers MCP tools and lifecycle hooks for **Antigravity** and **Claude Code**. However, developers using **Cursor** or **Zed** must currently copy and paste JSON configuration snippets by hand.

Extending `vifi setup` with `--cursor` and `--zed` flags (or auto-detecting their installations) will configure VoiceFi's MCP stdio server in one command.

### 2. Relevant Codebase Files
- `src/voicefi/integrations/discovery.py`: Add `detect_zed()` and enhance `detect_cursor()`.
- `src/voicefi/cli.py`: Update `cmd_setup()` to handle `--cursor`, `--zed`, and `--all`.
- `tests/test_editor_setup.py` *(New File)*: Config generation tests with temporary mock directories.

### 3. Step-by-Step Implementation Guidance
1. **Update Discovery**:
   - In `src/voicefi/integrations/discovery.py`, add `AgentToolDetector.detect_zed()` checking for `~/.config/zed/` (Linux/macOS) or `~/Library/Application Support/Zed/` (macOS).
2. **Implement Safe JSON Config Merging**:
   - For **Cursor** (`~/.cursor/mcp.json` or `.cursor/mcp.json`):
     ```json
     {
       "mcpServers": {
         "voicefi": {
           "command": "/path/to/voicefi",
           "args": ["mcp"]
         }
       }
     }
     ```
   - For **Zed** (`~/.config/zed/settings.json`):
     ```json
     {
       "context_servers": {
         "voicefi": {
           "command": {
             "path": "/path/to/voicefi",
             "args": ["mcp"]
           }
         }
       }
     }
     ```
   - *Crucial*: Read existing user configuration, merge `voicefi` into `mcpServers` / `context_servers`, and write back without stripping comments or other server entries.
3. **Wire into `cmd_setup`**:
   - Support `vifi setup --cursor`, `vifi setup --zed`, and include both when `vifi setup --all` is invoked.

### 4. Acceptance Criteria
- [ ] Running `vifi setup --cursor` generates or updates `.cursor/mcp.json` with the correct absolute executable path.
- [ ] Running `vifi setup --zed` updates Zed `settings.json` idempotently without corrupting other settings.
- [ ] Running `vifi setup --all` detects and configures all installed editors on the machine.

---

## 🔊 Issue 4: Directory-Based Custom Sound Effect Pack Loader

- **Difficulty**: 🟢 Easy (`Starter Issue`)
- **Area**: `SFX`, `Audio`, `Acoustics`
- **Labels**: `good first issue`, `audio`, `sfx`, `customization`
- **Target Release**: Phase 2

### 1. Description
VoiceFi features procedural comedy sound effects (rimshot, horn honk, sad trombone, applause, boing, crickets) synthesized via NumPy waveforms. 

Community members want the ability to drop custom sound files (`.wav` or `.mp3`) into `~/.voicefi/sfx/packs/<pack_name>/` and trigger them seamlessly via CLI (`vifi sfx <name> --pack <pack>`) and MCP (`voicefi_sfx(name="...", pack="...")`).

### 2. Relevant Codebase Files
- `src/voicefi/audio/sfx.py`: Sound effect registry and file loader.
- `src/voicefi/config.py`: Add `sfx_packs_dir` to `VoiceFiConfig`.
- `src/voicefi/cli.py`: Add pack discovery and listing subcommands to `cmd_sfx()`.
- `src/voicefi/mcp_server.py`: Add optional `pack` argument to `voicefi_sfx` MCP schema.

### 3. Step-by-Step Implementation Guidance
1. **Implement Sound Pack Scanner**:
   - In `src/voicefi/audio/sfx.py`, define `SFX_PACKS_DIR = Path.home() / ".voicefi" / "sfx" / "packs"`.
   - Implement `find_sound_file(name: str, pack: Optional[str] = None) -> Optional[Path]`:
     - If `pack` is specified: search `~/.voicefi/sfx/packs/<pack>/<name>.(wav|mp3)`.
     - If `pack` is omitted: search `~/.voicefi/sfx/<name>.(wav|mp3)`.
2. **Implement Fallback Playback**:
   - If a custom file is found: play via `sounddevice` or `subprocess.run(["afplay", str(path)])` (macOS) / `aplay` / `ffplay` (Linux).
   - If not found: fall back to built-in procedural NumPy generators (`_generate_rimshot`, `_generate_honk`, etc.).
3. **Add CLI Subcommands**:
   - `vifi sfx list-packs`: List all user packs found in `~/.voicefi/sfx/packs/`.
   - `vifi sfx play <name> --pack <pack>`: Play a specific custom sound effect.

### 4. Acceptance Criteria
- [ ] Placing `tada.wav` in `~/.voicefi/sfx/packs/retro/tada.wav` allows playing via `vifi sfx tada --pack retro`.
- [ ] If the specified sound does not exist, `vifi sfx` prints a clear list of available sounds.
- [ ] `vifi sfx list` lists both procedural sounds and discovered custom packs.
- [ ] Unit tests in `tests/test_chimes.py` verify custom pack resolution and fallback logic.

---

## 🔔 Issue 5: Cross-Platform Native Desktop Notification Fallback

- **Difficulty**: 🟢 Easy (`Starter Issue`)
- **Area**: `OS`, `UI`, `Linux`, `Windows`
- **Labels**: `good first issue`, `cross-platform`, `linux`, `windows`, `ui`
- **Target Release**: Phase 1.5

### 1. Description
VoiceFi sends desktop notifications when long-running AI agent tasks complete or when background builds finish. Currently, `src/voicefi/ui/notifications.py` uses `rumps.notification` and macOS `osascript` AppleScript dialogs. On Linux and Windows, these calls fail silently.

Implementing native notification utilities (`notify-send` on Linux, PowerShell toasts on Windows) gives non-macOS users desktop alert parity.

### 2. Relevant Codebase Files
- `src/voicefi/ui/notifications.py`: `show_notification(title, subtitle, message)`.
- `tests/test_notifications.py` *(New File)*: Cross-platform notification dispatch tests.

### 3. Step-by-Step Implementation Guidance
1. **Refactor `src/voicefi/ui/notifications.py`**:
   - Check `sys.platform`:
     - **macOS (`darwin`)**: Keep existing `rumps` and `osascript` logic.
     - **Linux (`linux`)**: Execute `notify-send "{title}" "{message}"` via `subprocess.run(["notify-send", title, message])`. If `notify-send` is not installed, fallback to stdout logging.
     - **Windows (`win32`)**: Execute PowerShell toast script or use optional `win10toast` if installed.
2. **Add Subprocess Safety**:
   - Sanitize all strings to prevent shell injection (`shlex.quote` or passing arguments directly as lists to `subprocess.run`).
   - Use `timeout=3` and suppress stderr/stdout.

### 4. Acceptance Criteria
- [ ] On Linux systems with `notify-send`, calling `show_notification("Build Complete", message="All tests passed")` displays a native Linux notification banner.
- [ ] On systems without notification daemons, the function returns `False` without throwing unhandled exceptions.
- [ ] Unit test with mocked `subprocess.run` verifies the exact command-line arguments dispatched across platforms.

---

## 🎙️ Issue 6: Rich Terminal Audio Waveform Meter for `vifi listen`

- **Difficulty**: 🟢 Easy (`Starter Issue`)
- **Area**: `CLI`, `Audio`, `DX`
- **Labels**: `good first issue`, `cli`, `rich`, `audio`
- **Target Release**: Phase 2

### 1. Description
When running `vifi listen` in the terminal, the user sees a simple text status line. Adding a real-time ASCII / Unicode volume and frequency level meter (e.g. ` ▂▃▅▆▇█`) powered by RMS energy ticks makes terminal voice capture engaging and visually informative.

### 2. Relevant Codebase Files
- `src/voicefi/audio/recorder.py`: `on_listening_tick` callback interface.
- `src/voicefi/cli.py`: `cmd_listen(args)`.

### 3. Step-by-Step Implementation Guidance
1. **Create Waveform Meter Helper**:
   - Implement an RMS-to-block character mapper:
     ```python
     BARS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
     def render_energy_meter(rms: float, max_bars: int = 15) -> str:
         level = min(int(rms * 100), max_bars)
         return "".join(BARS[min(i, len(BARS)-1)] for i in range(level))
     ```
2. **Hook into Recorder Callback**:
   - Pass an `on_energy_tick` callback to `AudioRecorder.listen()` in `cmd_listen()`.
   - Update terminal line dynamically using `\r` (carriage return) without scrolling.

### 4. Acceptance Criteria
- [ ] Running `vifi listen` displays a dynamic, real-time volume bar that fluctuates as the user speaks.
- [ ] Pressing `Ctrl+C` or reaching silence timeout cleanly restores cursor position.

---

## 🚀 How to Claim and Submit an Issue

1. **Find an Unassigned Issue**: Browse the list above or check our [GitHub Issues](https://github.com/atxatlarge-code/voicefi/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
2. **Comment to Claim**: Drop a comment: *"I would like to work on this issue! #<IssueNumber>"*.
3. **Follow the Development Setup**: Read [CONTRIBUTING.md](../CONTRIBUTING.md) to set up your local `.venv` and test harness.
4. **Submit Your Pull Request**: Reference the issue in your PR body (`Fixes #<number>`) and ensure all CI checks pass.
5. **Get Rewarded**: Eligible issues earn badges and cash bounties via the [VoiceFi Plugin Bounty Program](./COMMUNITY_GROWTH.md)!
