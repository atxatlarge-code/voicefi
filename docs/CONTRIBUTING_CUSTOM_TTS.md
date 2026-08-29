# Contributing Custom TTS Engines & Voice Providers

VoiceFi is engineered with a modular, provider-agnostic Text-to-Speech (TTS) architecture. Whether you are integrating a local neural engine (such as Piper, Kokoro, or XTTS), a cloud-based API (such as OpenAI TTS, Cartesia, or PlayHT), or a proprietary voice cloning pipeline, this guide provides the end-to-end blueprint for building, registering, locking, and testing custom TTS providers.

---

## 1. Architectural Overview

All TTS providers in VoiceFi inherit from the abstract base class `BaseTTS` defined in `src/voicefi/tts/base.py`. 

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           VoiceFi TTS Subsystem                                │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│   CLI / MCP / Agent Hook                                                       │
│          │                                                                     │
│          ▼                                                                     │
│   `get_tts_engine(config, agent_name, voice_override)`  (src/voicefi/tts/__init__.py)
│          │                                                                     │
│          ▼                                                                     │
│   ┌────────────────────────────────────────────────────────────────────────┐   │
│   │                      `BaseTTS` Abstract Class                          │   │
│   │                     (src/voicefi/tts/base.py)                          │   │
│   │                                                                        │   │
│   │  • `speak(text, block=True)`        • `stop()`                         │   │
│   │  • `stream_speak(text, block=True)` • `speak_to_file(text, path)`      │   │
│   │  • `synthesize_to_file(text, path)`                                    │   │
│   └──────┬──────────────────────┬──────────────────────┬───────────────────┘   │
│          │                      │                      │                       │
│          ▼                      ▼                      ▼                       │
│   `MacSayTTS`            `EdgeTTS`              `ElevenLabsTTS`                │
│   (macOS Native)        (Microsoft Neural)     (ElevenLabs Cloud)              │
│          │                      │                      │                       │
│          ▼                      ▼                      ▼                       │
│   `F5TTS`                `CustomNeuralTTS`      (Your Provider Here)           │
│   (Diffusion Clone)     (e.g., Piper / OpenAI)                                 │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

### The `BaseTTS` Interface

Every engine subclass must adhere to `src/voicefi/tts/base.py`:

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

class BaseTTS(ABC):
    """Abstract interface for all VoiceFi TTS engines."""

    def __init__(self, *args, **kwargs):
        # Automatically registers instance in global weakset for emergency stop handling
        _ACTIVE_TTS_ENGINES.add(self)

    @abstractmethod
    def speak(self, text: str, block: bool = True) -> None:
        """
        Synthesize and speak the provided text aloud.
        
        Args:
            text: Text string to speak.
            block: If True, blocks until audio finishes playing through speakers.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        Immediately interrupt and cancel any ongoing speech synthesis or playback.
        """
        pass

    def stream_speak(self, text: str, block: bool = True) -> None:
        """
        Stream and synthesize audio with minimal Time-To-First-Byte (TTFB) latency.
        Defaults to `speak(text, block=block)` if streaming is not implemented.
        """
        self.speak(text, block=block)

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """
        Synthesize speech directly to an audio file (e.g. WAV/MP3) without speaker playback.
        Used for silent benchmarks (`vifi ping`), diagnostics, and test suites.
        
        Returns:
            True if synthesis succeeded and file was created, False otherwise.
        """
        return False

    async def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """
        Asynchronous variant of `speak_to_file` for async pipelines.
        """
        return self.speak_to_file(text, output_path)
```

---

## 2. Cross-Process Concurrency & Speech Locking

In a multi-agent coding environment, multiple processes concurrently interact with the voice layer:
- Antigravity Stop Hooks running in IDE background workers
- Claude Code hooks dispatching task results
- Background subagents reporting completed code modifications
- CLI invocations (`vifi speak`, `vifi duel`, `vifi memo`)

To prevent multiple agents or processes from speaking simultaneously or clipping each other, VoiceFi uses an inter-process synchronization harness.

### 2.1 The `speech_turn_lock` Context Manager

`speech_turn_lock` (`src/voicefi/tts/base.py`) orchestrates thread and process mutual exclusion:

```python
from voicefi.tts.base import speech_turn_lock

with speech_turn_lock(text="Refactoring complete.", agent_name="antigravity", persona_name="Viv"):
    # 1. Acquires cross-process advisory lock (/tmp/voicefi_speech.lock) via fcntl.flock
    # 2. Checks deduplication cache (/tmp/voicefi_recent_speech.json) within a 6-second window
    # 3. Sets speaking status (/tmp/voicefi_speaking.status)
    # 4. Updates Dynamic Island HUD state (/tmp/voicefi_hud_state.json)
    # 5. Waits for previous audio card emissions to clear
    # 6. Activates Escape-key listener to stop speech on user Esc press
    engine.speak("Refactoring complete.", block=True)
    # 7. On exit: applies 0.25s acoustic decay margin for room reverb dissipation
    # 8. Clears speaking status and unlocks file descriptor
```

### 2.2 Shared Status Files & Locks

| File Path | Component | Purpose |
| :--- | :--- | :--- |
| `/tmp/voicefi_speech.lock` | `fcntl.flock(LOCK_EX)` | Cross-process mutual exclusion mutex preventing concurrent speech |
| `/tmp/voicefi_speaking.status` | JSON payload `{"pid", "timestamp", "text", "agent_name", "persona_name"}` | Real-time speaking indicator queried by VAD to suppress microphone bleed |
| `/tmp/voicefi_audio_playing.status` | String `"<pid>:<timestamp>"` | Physical sound card emission tracker |
| `/tmp/voicefi_hud_state.json` | JSON payload | Inter-process state bridge for macOS Dynamic Island floating HUD |
| `/tmp/voicefi_recent_speech.json` | JSON list `[{"norm": "...", "timestamp": ...}]` | Speech deduplication cache preventing duplicate voice notifications |

### 2.3 Duplicate Speech Suppression

If identical or near-identical text was spoken by any agent within the last 6.0 seconds, `speech_turn_lock` raises `DuplicateSpeechSuppressed`. This prevents duplicate spoken updates when an IDE hook and subagent emit matching completion messages:

```python
from voicefi.tts.base import DuplicateSpeechSuppressed

try:
    with speech_turn_lock(text=message, agent_name="antigravity", persona_name="Viv"):
        engine.speak(message, block=True)
except DuplicateSpeechSuppressed:
    # Safely ignored — user already heard this announcement
    pass
```

### 2.4 Emergency Stop & HUD Dismissal

VoiceFi registers all instantiated engines in `_ACTIVE_TTS_ENGINES` (a `weakref.WeakSet`). When `stop_all_speech()` is called (via `vifi stop`, MCP `voicefi_stop`, or pressing the `Esc` key during speech):
1. `engine.stop()` is invoked on all active engine instances.
2. macOS `killall say` and `killall afplay` subprocesses are terminated.
3. Status files `/tmp/voicefi_speaking.status` and `/tmp/voicefi_audio_playing.status` are unlinked.
4. The floating Dynamic Island HUD is transitioned back to idle.

---

## 3. Step-by-Step Implementation Tutorial

Let's walk through creating a new custom neural TTS provider: `CustomNeuralTTS` (e.g. OpenAI TTS or a custom local Piper neural synthesis daemon).

### Step 1: Create the Provider Class

Create `src/voicefi/tts/custom_neural.py`:

```python
"""
Custom Neural TTS Provider for VoiceFi.
Synthesizes speech using a custom local neural endpoint or cloud API.
"""

import os
import sys
import time
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

from voicefi.tts.base import (
    BaseTTS,
    speech_turn_lock,
    set_agent_audio_playing,
    DuplicateSpeechSuppressed,
)


class CustomNeuralTTS(BaseTTS):
    """Custom Neural TTS Engine implementation."""

    def __init__(
        self,
        voice: str = "nova",
        rate: Optional[int] = 200,
        volume: float = 1.0,
        api_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        agent_name: str = "VoiceFi",
        persona_name: Optional[str] = None,
    ):
        super().__init__()
        self.voice = voice
        self.rate = rate or 200
        self.volume = max(0.1, min(volume, 2.0))
        self.api_key = api_key or os.getenv("CUSTOM_TTS_API_KEY", "")
        self.endpoint_url = endpoint_url or "https://api.example.com/v1/audio/speech"
        self.agent_name = agent_name
        self.persona_name = persona_name or voice
        self._current_proc: Optional[subprocess.Popen] = None
        self._stopped = False

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize text and play aloud through speakers with speech locking."""
        if not text or not text.strip():
            return

        clean_text = text.strip()
        self._stopped = False

        try:
            with speech_turn_lock(
                text=clean_text,
                agent_name=self.agent_name,
                persona_name=self.persona_name,
            ):
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    temp_audio_path = Path(tmp.name)

                try:
                    success = self.speak_to_file(clean_text, temp_audio_path)
                    if not success or not temp_audio_path.is_file() or temp_audio_path.stat().st_size == 0:
                        raise RuntimeError(f"Failed to synthesize audio for text: {clean_text[:30]}")

                    if self._stopped:
                        return

                    # Playback via macOS afplay
                    self._play_audio_file(temp_audio_path, block=block)
                finally:
                    temp_audio_path.unlink(missing_ok=True)

        except DuplicateSpeechSuppressed:
            return

    def stop(self) -> None:
        """Interrupt active synthesis and audio playback."""
        self._stopped = True
        if self._current_proc and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
                self._current_proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._current_proc.kill()
                except Exception:
                    pass
        self._current_proc = None
        set_agent_audio_playing(False)

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize audio directly to output_path without speaker emission."""
        try:
            # --- Synthesis implementation ---
            # Replace with your actual REST request, Piper CLI call, or SDK invocation
            # Here we illustrate writing raw audio or calling an external tool:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Example: Mocking or invoking custom synthesizer
            # In production, call your HTTP client or neural model inference here:
            self._synthesize_audio_payload(text, output_path)
            return output_path.is_file() and output_path.stat().st_size > 0
        except Exception as e:
            print(f"[CustomNeuralTTS] Error during synthesis: {e}", file=sys.stderr)
            return False

    def _synthesize_audio_payload(self, text: str, output_path: Path) -> None:
        """Generate audio payload into output_path."""
        # Realistic implementation stub: generate valid 16-bit PCM WAV
        import wave
        import numpy as np

        sample_rate = 24000
        duration = max(0.5, len(text) * 0.05)  # approximate duration
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        # Gentle pleasant tone carrier for mock/test fallback
        audio = 0.3 * np.sin(2 * np.pi * 440.0 * t) * np.exp(-t / duration)
        pcm_data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data.tobytes())

    def _play_audio_file(self, audio_path: Path, block: bool = True) -> None:
        """Play WAV audio file via afplay with state tracking."""
        if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("VOICEFI_TESTING") == "1":
            return

        cmd = ["afplay", "-v", str(self.volume), str(audio_path)]
        set_agent_audio_playing(True)
        try:
            self._current_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if block:
                self._current_proc.wait()
        finally:
            set_agent_audio_playing(False)
            self._current_proc = None
```

---

### Step 2: Register in Engine Factory (`src/voicefi/tts/__init__.py`)

Import your provider and register it in `get_tts_engine`:

```python
# In src/voicefi/tts/__init__.py
from voicefi.tts.custom_neural import CustomNeuralTTS

def get_tts_engine(
    config: VoiceFiConfig,
    agent_name: Optional[str] = None,
    voice_override: Optional[str] = None,
    provider_override: Optional[str] = None,
    rate_override: Optional[any] = None,
    is_focused: bool = True,
) -> BaseTTS:
    provider, voice, rate = config.resolve_voice(agent_name, is_focused=is_focused)

    if provider_override:
        provider = provider_override
    if voice_override:
        voice = voice_override
        persona = find_persona(voice_override)
        if persona:
            voice = persona.id
            if not provider_override:
                provider = persona.provider

    provider = provider.lower()

    # --- Add your provider branch ---
    if provider in ("custom_neural", "custom_tts"):
        eng = CustomNeuralTTS(
            voice=voice,
            rate=rate,
            volume=getattr(config.tts, "volume", 1.0),
            api_key=getattr(config.tts, "custom_api_key", ""),
            endpoint_url=getattr(config.tts, "custom_endpoint_url", None),
            agent_name=agent_name or "VoiceFi",
        )
    elif provider == "elevenlabs":
        ...
```

---

### Step 3: Add Personas to Catalog (`src/voicefi/tts/catalog.py`)

Add your curated voice personas to `CURATED_PERSONAS`:

```python
# In src/voicefi/tts/catalog.py

CURATED_PERSONAS: List[VoicePersona] = [
    # ... existing personas ...
    VoicePersona(
        id="custom-neural-nova",
        name="Nova",
        provider="custom_neural",
        gender="Female",
        locale="en-US",
        style="Warm, articulate, natural studio voice",
        sample_text="Hey! I'm Nova, powered by the custom neural voice engine.",
        recommended_role="Antigravity Primary Agent",
    ),
    VoicePersona(
        id="custom-neural-onyx",
        name="Onyx",
        provider="custom_neural",
        gender="Male",
        locale="en-US",
        style="Deep, authoritative, resonant architectural narrator",
        sample_text="System architecture validated. All test boundaries operational.",
        recommended_role="Architect / Code Reviewer",
    ),
]
```

---

### Step 4: Update Pydantic Configuration (`src/voicefi/config.py`)

Update `TTSConfig` to include your provider in the `Literal` type and define optional settings:

```python
# In src/voicefi/config.py

class TTSConfig(BaseModel):
    provider: Literal["mac_say", "edge_tts", "elevenlabs", "f5_tts", "local_clone", "custom_neural"] = "edge_tts"
    voice: str = "en-US-AvaNeural"
    rate: Optional[int] = 200
    volume: float = 1.0
    streaming: bool = True
    elevenlabs_api_key: Optional[str] = ""
    elevenlabs_voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM"
    
    # Custom Neural Provider configuration options
    custom_api_key: Optional[str] = ""
    custom_endpoint_url: Optional[str] = "https://api.example.com/v1/audio/speech"
```

---

## 4. Testing Your Custom TTS Provider

VoiceFi enforces comprehensive test coverage for all audio providers. Write unit tests using `pytest` and mock audio execution.

### Creating Unit Tests (`tests/test_custom_neural_tts.py`)

```python
"""
Unit tests for CustomNeuralTTS provider.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from voicefi.tts.custom_neural import CustomNeuralTTS
from voicefi.tts.base import (
    speech_turn_lock,
    is_agent_speaking,
    set_agent_speaking,
    clear_recent_speech_history,
    DuplicateSpeechSuppressed,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean speaking lock state before and after each test."""
    set_agent_speaking(False)
    clear_recent_speech_history()
    yield
    set_agent_speaking(False)
    clear_recent_speech_history()


def test_custom_tts_initialization():
    """Verify provider initializes with expected defaults."""
    engine = CustomNeuralTTS(voice="nova", rate=180, volume=0.9)
    assert engine.voice == "nova"
    assert engine.rate == 180
    assert engine.volume == 0.9
    assert engine.agent_name == "VoiceFi"


def test_custom_tts_speak_to_file():
    """Verify offline file synthesis generates a valid non-empty audio file."""
    engine = CustomNeuralTTS(voice="nova")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_file = Path(tmp.name)

    try:
        success = engine.speak_to_file("Testing audio generation.", out_file)
        assert success is True
        assert out_file.is_file()
        assert out_file.stat().st_size > 100
    finally:
        out_file.unlink(missing_ok=True)


def test_custom_tts_speak_with_lock():
    """Verify speak executes cleanly under speech_turn_lock."""
    engine = CustomNeuralTTS(voice="nova")
    
    with patch.object(engine, "_play_audio_file") as mock_play:
        engine.speak("Unit test message.", block=True)
        assert mock_play.called


def test_custom_tts_duplicate_suppression():
    """Verify rapid consecutive identical speech is suppressed."""
    engine = CustomNeuralTTS(voice="nova")
    
    with patch.object(engine, "_play_audio_file") as mock_play:
        # First call succeeds
        engine.speak("Identical notification text.", block=True)
        assert mock_play.call_count == 1
        
        # Immediate second call is suppressed by speech_turn_lock
        engine.speak("Identical notification text.", block=True)
        assert mock_play.call_count == 1  # Not incremented


def test_custom_tts_stop():
    """Verify stop terminates active subprocess."""
    engine = CustomNeuralTTS(voice="nova")
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    engine._current_proc = mock_proc
    
    engine.stop()
    assert mock_proc.terminate.called
    assert engine._stopped is True
```

Run your tests:
```bash
pytest tests/test_custom_neural_tts.py -v
```

---

## 5. Contributor Best Practices Checklist

- [ ] **Inherit from `BaseTTS`**: Ensure all abstract methods (`speak`, `stop`) are fully implemented.
- [ ] **Locking Compliance**: Always wrap speech execution in `speech_turn_lock(text=..., agent_name=..., persona_name=...)`.
- [ ] **Offline File Synthesis**: Implement `speak_to_file()` to support silent benchmarking (`vifi ping`) and test fixtures without audio hardware dependencies.
- [ ] **Audio State Cleanliness**: Ensure `set_agent_audio_playing(False)` is called in `finally:` blocks or `stop()`.
- [ ] **Test Isolation**: Guarantee that unit tests run safely in CI/CD without requiring real audio output devices (respect `os.getenv("PYTEST_CURRENT_TEST")`).
