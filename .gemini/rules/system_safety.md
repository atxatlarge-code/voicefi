# VoiceFi System Safety & macOS Resource Guardrails

## 1. Automated Testing & Pytest Safety
- **Headless Enforcement**: Automated tests must ALWAYS run with `VOICEFI_HEADLESS=1` and `VOICEFI_TESTING=1`. Tests must never spawn live AppKit panels, Cocoa windows, or CoreAudio playback onto the host's active macOS `WindowServer`.
- **Targeted Test Execution**: NEVER run the entire 1,176+ test suite (`pytest tests/`) indiscriminately during rapid development. Always run targeted tests for the specific module being modified (e.g. `pytest tests/test_foo.py`).
- **Media Player & Window Server Isolation**: `tests/conftest.py` contains automated safety fixtures (`guard_windowserver_display_safety`, `reset_media_detection_guard`, `prevent_real_audio_playback`). Never disable these fixtures.

## 2. On-Device LLM & MLX GPU Memory Guardrails
- **Metal Cache Clearance**: Any script running local MLX models (e.g. Qwen 2.5 Coder 32B/14B, Gemma) must explicitly clear the Metal GPU cache after inference using:
  ```python
  import mlx.core as mx

  mx.metal.clear_cache()
  ```
- **Process Isolation**: Local inference jobs must run in self-contained worker processes so that 18–20 GB Unified Memory buffers are immediately reclaimed upon process exit.
- **Never Concurrently Run Heavy Tests & 32B Models**: Do not launch background test runners or stress tests while a 32B local model is resident in Metal GPU memory, to prevent starving macOS `WindowServer` and triggering userspace watchdog reboots.
