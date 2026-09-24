"""
Voice Training, Acoustic Analysis, and Instant Voice Cloning Manager for VoiceFi.
Enables users to record or import voice samples, analyze acoustic characteristics,
train/clone custom voices via ElevenLabs IVC or local acoustic profiling, and assign
them to Antigravity and subagents.
"""

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
from pydantic import BaseModel, Field

from voicefi.config import AgentVoiceProfile, VoiceFiConfig, save_config
from voicefi.tts.elevenlabs import ElevenLabsTTS


TRAINING_PROMPTS = [
    {
        "id": "warmup",
        "title": "Conversational Intro",
        "text": "Hey there! I am recording my voice so my AI coding agents can pair program and talk with me in real-time.",
    },
    {
        "id": "technical",
        "title": "Technical & Code Flow",
        "text": "Antigravity, let's refactor the asynchronous database connection pool and run the complete test suite.",
    },
    {
        "id": "decisive",
        "title": "Decisions & Architecture",
        "text": "The architecture looks clean. Let's merge the branch, tag release version one point zero, and deploy to production.",
    },
    {
        "id": "confirmation",
        "title": "Quick Confirmation",
        "text": "Got it. All unit tests passed without errors, everything looks solid and ready to ship.",
    },
]


def get_clones_dir() -> Path:
    """Return the root directory for cloned voices (~/.voicefi/cloned_voices)."""
    d = Path.home() / ".voicefi" / "cloned_voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ClonedVoiceProfile(BaseModel):
    """Metadata and acoustic profile for a user-trained voice clone."""

    id: str
    name: str
    provider: str = "elevenlabs"  # "elevenlabs", "edge_tts", "mac_say"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str = ""
    sample_paths: List[str] = Field(default_factory=list)
    acoustic_metrics: Dict[str, Any] = Field(default_factory=dict)
    persona_prompt: str = ""
    labels: Dict[str, str] = Field(default_factory=dict)
    assigned_agents: List[str] = Field(default_factory=list)
    calibrated_voice: Optional[str] = None
    calibrated_rate: Optional[int] = None
    calibrated_pitch: Optional[str] = "+0Hz"

    @property
    def vocal_range(self) -> str:
        return self.acoustic_metrics.get("vocal_range", "Natural")

    @property
    def avg_pitch_hz(self) -> float:
        return float(self.acoustic_metrics.get("avg_pitch_hz", 140.0))

    @property
    def suggested_neural_base(self) -> str:
        return self.acoustic_metrics.get(
            "suggested_neural_base", self.calibrated_voice or "Ava (Premium)"
        )


def estimate_pitch_f0(audio_data: np.ndarray, sample_rate: int = 16000) -> float:
    """
    Estimate fundamental frequency (F0 in Hz) using normalized autocorrelation.
    Clamps search to human speech range (70 Hz to 450 Hz).
    """
    if len(audio_data) < sample_rate // 20:
        return 0.0

    # Work on a center slice of speech with good energy
    frame_size = int(sample_rate * 0.05)  # 50ms frame
    num_frames = len(audio_data) // frame_size
    f0_estimates = []

    min_lag = int(sample_rate / 450)  # ~450 Hz
    max_lag = int(sample_rate / 70)  # ~70 Hz

    for i in range(min(num_frames, 20)):
        start = i * frame_size
        frame = audio_data[start : start + frame_size]
        # Skip low-energy frames
        if np.sqrt(np.mean(frame**2)) < 0.01:
            continue

        # Autocorrelation
        corr = np.correlate(frame, frame, mode="full")
        corr = corr[len(corr) // 2 :]

        if max_lag < len(corr):
            search_window = corr[min_lag:max_lag]
            if len(search_window) > 0 and np.max(search_window) > 0:
                peak_idx = np.argmax(search_window) + min_lag
                if peak_idx > 0:
                    f0 = sample_rate / peak_idx
                    if 70 <= f0 <= 450:
                        f0_estimates.append(f0)

    if not f0_estimates:
        return 140.0  # default median human pitch

    return float(np.median(f0_estimates))


def analyze_audio_acoustics(audio_paths: List[Path]) -> Dict[str, Any]:
    """
    Compute acoustic metrics across one or more audio sample files.
    Calculates total duration, RMS energy, estimated pitch (F0), and voice classification.
    """
    total_duration = 0.0
    energies = []
    pitches = []

    for p in audio_paths:
        if not p.exists():
            continue
        try:
            data, sr = sf.read(str(p))
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            duration = len(data) / sr
            total_duration += duration

            rms = float(np.sqrt(np.mean(data**2)))
            energies.append(rms)

            f0 = estimate_pitch_f0(data, sample_rate=sr)
            if f0 > 0:
                pitches.append(f0)
        except Exception as e:
            print(f"[Acoustics] Warning reading {p}: {e}")

    avg_pitch = float(np.mean(pitches)) if pitches else 140.0
    avg_energy = float(np.mean(energies)) if energies else 0.05

    # Vocal range categorization
    if avg_pitch < 115:
        category = "Bass / Deep"
        suggested_base = "en-US-ChristopherNeural"
        suggested_pitch = "-10Hz"
    elif avg_pitch < 155:
        category = "Baritone / Grounded"
        suggested_base = "en-US-GuyNeural"
        suggested_pitch = "+0Hz"
    elif avg_pitch < 195:
        category = "Tenor / Warm"
        suggested_base = "en-AU-WilliamNeural"
        suggested_pitch = "+5Hz"
    elif avg_pitch < 235:
        category = "Alto / Clear"
        suggested_base = "en-GB-SoniaNeural"
        suggested_pitch = "+0Hz"
    else:
        category = "Soprano / Bright"
        suggested_base = "en-US-AriaNeural"
        suggested_pitch = "+10Hz"

    return {
        "sample_count": len(audio_paths),
        "total_duration_seconds": round(total_duration, 2),
        "avg_pitch_hz": round(avg_pitch, 1),
        "vocal_range": category,
        "avg_rms_energy": round(avg_energy, 4),
        "suggested_neural_base": suggested_base,
        "suggested_pitch_offset": suggested_pitch,
        "quality_score": "High"
        if total_duration >= 15.0
        else ("Good" if total_duration >= 5.0 else "Fair"),
    }


def generate_persona_prompt(
    voice_name: str, acoustic_info: Dict[str, Any], custom_traits: Optional[Dict[str, str]] = None
) -> str:
    """
    Generate an AI persona prompt reflecting the user's authentic voice,
    cadence, and conversational style so agents truly "talk like them".
    """
    traits = custom_traits or {}
    tone = traits.get("tone", "pragmatic, focused, and conversational")
    tempo = traits.get("tempo", "medium-fast with crisp technical delivery")
    catchphrases = traits.get("catchphrases", "Looks solid, let's ship it, running tests now")
    brevity = traits.get("brevity", "direct, concise, no unnecessary fluff")

    vocal_range = acoustic_info.get("vocal_range", "Natural Conversational")

    return (
        f"# Persona Profile: {voice_name}\n"
        f"You speak and communicate in the authentic personal style of {voice_name}.\n\n"
        f"## Acoustic & Delivery Traits\n"
        f"- Vocal Character: {vocal_range}\n"
        f"- Speaking Cadence: {tempo}\n"
        f"- Tone & Demeanor: {tone}\n"
        f"- Conciseness: {brevity}\n\n"
        f"## Conversational Phrasing & Style\n"
        f"- Keep spoken explanations punchy, pragmatic, and developer-centric.\n"
        f"- Preferred phrases/idioms: {catchphrases}.\n"
        f"- Avoid robotic filler phrases; speak naturally as if pair-programming together.\n"
    )


class VoiceCloneManager:
    """Manages the full lifecycle of custom voice training, cloning, and persona profiles."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or get_clones_dir()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def list_cloned_voices(self) -> List[ClonedVoiceProfile]:
        """Load and return all saved cloned voice profiles."""
        profiles = []
        for p_dir in sorted(self.root_dir.iterdir()):
            if p_dir.is_dir():
                prof_file = p_dir / "profile.json"
                if prof_file.is_file():
                    try:
                        with open(prof_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        profiles.append(ClonedVoiceProfile(**data))
                    except Exception as e:
                        print(f"[VoiceCloneManager] Error reading {prof_file}: {e}")
        return profiles

    def get_cloned_voice(self, name_or_id: str) -> Optional[ClonedVoiceProfile]:
        """Find a cloned profile by name, exact ID, calibrated voice, or slug (case-insensitive)."""
        if not name_or_id:
            return None
        target = str(name_or_id).lower().strip()
        for p in self.list_cloned_voices():
            if (
                p.id.lower() == target
                or p.name.lower() == target
                or (p.calibrated_voice and p.calibrated_voice.lower() == target)
                or target in p.id.lower()
                or target in p.name.lower()
            ):
                return p

        # Fallback alias mapping for documentary broadcaster
        if target in (
            "attenborough",
            "sir david attenborough",
            "david attenborough",
            "documentary",
            "documentary_broadcaster",
        ):
            for p in self.list_cloned_voices():
                if any(
                    k in p.id.lower() or k in p.name.lower()
                    for k in ("documentary", "broadcaster", "attenborough")
                ):
                    return p

        return None

    get_voice = get_cloned_voice

    def save_cloned_profile(self, profile: ClonedVoiceProfile) -> Path:
        """Save profile metadata to its directory."""
        slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in profile.name.lower())
        p_dir = self.root_dir / slug
        p_dir.mkdir(parents=True, exist_ok=True)
        prof_file = p_dir / "profile.json"
        with open(prof_file, "w", encoding="utf-8") as f:
            json.dump(profile.model_dump(), f, indent=2)
        return prof_file

    def import_samples(self, voice_name: str, file_paths: List[Path]) -> List[Path]:
        """
        Copy user-provided audio files into the profile's dedicated samples directory.
        Converts non-WAV formats to standard 16kHz/24kHz WAV when needed.
        """
        slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in voice_name.lower())
        samples_dir = self.root_dir / slug / "samples"
        samples_dir.mkdir(parents=True, exist_ok=True)

        copied = []
        for i, src in enumerate(file_paths):
            src_path = Path(src).expanduser().resolve()
            if not src_path.exists():
                continue
            dest_name = f"sample_{i + 1:02d}_{src_path.name}"
            dest_path = samples_dir / dest_name
            try:
                # Read with soundfile and rewrite to clean WAV format
                data, sr = sf.read(str(src_path))
                sf.write(str(dest_path), data, sr)
                copied.append(dest_path)
            except Exception:
                # Fallback to direct copy
                shutil.copy2(src_path, dest_path)
                copied.append(dest_path)

        return copied

    def train_voice(
        self,
        name: str,
        sample_paths: List[Path],
        api_key: Optional[str] = None,
        description: str = "",
        custom_traits: Optional[Dict[str, str]] = None,
        labels: Optional[Dict[str, str]] = None,
        provider_preference: Optional[str] = None,
        ref_text: Optional[str] = None,
    ) -> ClonedVoiceProfile:
        """
        Train / Clone a voice from audio samples.
        - Ingests samples to ~/.voicefi/cloned_voices/<name>/samples/
        - Extracts acoustic features & vocal range
        - Auto-transcribes reference audio via local STT if ref_text omitted
        - Configures local Kokoro, F5-TTS, or ElevenLabs IVC profile
        - Generates persona style prompt
        - Persists profile
        """
        if not name or not name.strip():
            raise ValueError("Voice name cannot be empty.")
        if not sample_paths:
            raise ValueError("At least one audio sample is required.")

        clean_name = name.strip()
        slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in clean_name.lower())

        # 1. Ingest audio samples
        stored_samples = self.import_samples(clean_name, sample_paths)
        if not stored_samples:
            raise ValueError("No valid audio samples could be imported.")

        # 2. Extract acoustic features
        acoustics = analyze_audio_acoustics(stored_samples)

        # 3. Provider Resolution: Kokoro, ElevenLabs IVC, F5-TTS, or Calibrated Neural
        voice_id = f"cloned_{slug}"
        if provider_preference in ("kokoro", "kokoro_onnx"):
            provider = "kokoro"
        elif provider_preference in ("f5_tts", "local_clone", "luxtts"):
            provider = "f5_tts"
        elif api_key:
            provider = "elevenlabs"
        elif provider_preference:
            provider = provider_preference
        else:
            provider = "local_clone"

        labels_dict = labels or {}
        labels_dict.setdefault("cloned_by", "voicefi")
        labels_dict.setdefault("vocal_range", acoustics.get("vocal_range", "Unknown"))

        # Auto-transcribe reference audio if not provided
        if ref_text and ref_text.strip():
            labels_dict["ref_text"] = ref_text.strip()
        elif "ref_text" not in labels_dict:
            if os.environ.get("VOICEFI_MOCK_AUDIO") == "1" or os.environ.get("VOICEFI_TESTING") == "1":
                if TRAINING_PROMPTS:
                    labels_dict["ref_text"] = TRAINING_PROMPTS[0]["text"]
            else:
                try:
                    from voicefi.stt import get_stt_engine
                    from voicefi.config import load_config

                    cfg = load_config()
                    stt = get_stt_engine(cfg)
                    transcribed = stt.transcribe(str(stored_samples[0]))
                    if transcribed and transcribed.strip():
                        labels_dict["ref_text"] = transcribed.strip()
                    elif TRAINING_PROMPTS:
                        labels_dict["ref_text"] = TRAINING_PROMPTS[0]["text"]
                except Exception:
                    if TRAINING_PROMPTS:
                        labels_dict["ref_text"] = TRAINING_PROMPTS[0]["text"]

        if api_key and provider == "elevenlabs":
            try:
                resp = ElevenLabsTTS.add_voice(
                    api_key=api_key,
                    name=clean_name,
                    audio_file_paths=stored_samples,
                    description=description or f"Custom cloned voice of {clean_name} (VoiceFi)",
                    labels=labels_dict,
                )
                voice_id = resp.get("voice_id", voice_id)
                provider = "elevenlabs"
            except Exception as e:
                print(
                    f"[VoiceCloneManager] ElevenLabs IVC failed ({e}), falling back to local open-source profile."
                )
                provider = "local_clone"

        # 4. Generate persona prompt
        persona_prompt = generate_persona_prompt(clean_name, acoustics, custom_traits)

        # 5. Build and save profile
        profile = ClonedVoiceProfile(
            id=voice_id,
            name=clean_name,
            provider=provider,
            description=description or f"Custom cloned voice of {clean_name}",
            sample_paths=[str(p) for p in stored_samples],
            acoustic_metrics=acoustics,
            persona_prompt=persona_prompt,
            labels=labels_dict,
            calibrated_voice=acoustics.get("suggested_neural_base"),
            calibrated_rate=200,
            calibrated_pitch=acoustics.get("suggested_pitch_offset", "+0Hz"),
        )

        self.save_cloned_profile(profile)
        return profile

    def delete_cloned_voice(
        self,
        name_or_id: str,
        delete_from_elevenlabs: bool = False,
        api_key: Optional[str] = None,
    ) -> bool:
        """Delete a cloned voice profile locally and optionally from ElevenLabs."""
        profile = self.get_cloned_voice(name_or_id)
        if not profile:
            return False

        if delete_from_elevenlabs and profile.provider == "elevenlabs" and api_key:
            ElevenLabsTTS.delete_voice(api_key, profile.id)

        slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in profile.name.lower())
        p_dir = self.root_dir / slug
        if p_dir.exists() and p_dir.is_dir():
            shutil.rmtree(p_dir)
            return True
        return False

    def assign_to_agent(
        self,
        voice_name_or_id: str,
        target_agent: str,
        config: VoiceFiConfig,
    ) -> Tuple[str, str]:
        """
        Assign the cloned voice to an agent or subagent in VoiceFiConfig and save.
        Returns (target_agent, resolved_voice_id).
        """
        profile = self.get_cloned_voice(voice_name_or_id)
        if not profile:
            raise ValueError(f"Cloned voice '{voice_name_or_id}' not found.")

        target = target_agent.lower().strip()
        voice_profile = AgentVoiceProfile(
            voice=profile.id
            if profile.provider in ("elevenlabs", "f5_tts", "local_clone")
            else (profile.calibrated_voice or "en-US-AvaNeural"),
            provider=profile.provider,
            offline_voice=profile.calibrated_voice or "Ava (Premium)",
            rate=profile.calibrated_rate or 200,
            pitch=profile.calibrated_pitch or "+0Hz",
            description=f"Cloned voice of {profile.name}",
        )

        if profile.provider in ("f5_tts", "local_clone") and profile.sample_paths:
            voice_profile.f5_ref_audio = profile.sample_paths[0]
            voice_profile.f5_ref_text = profile.labels.get("ref_text")

        subagent_roles = {"researcher", "debugger", "architect", "tester", "writer", "analyst"}

        if target in ("default", "global"):
            config.tts.voice = voice_profile.voice
            config.tts.provider = voice_profile.provider or config.tts.provider
            if profile.provider == "elevenlabs":
                config.tts.elevenlabs_voice_id = profile.id
            elif profile.provider in ("f5_tts", "local_clone"):
                if profile.sample_paths:
                    config.tts.f5_ref_audio = profile.sample_paths[0]
                    config.tts.f5_ref_text = profile.labels.get("ref_text")
        elif target in subagent_roles or target.startswith("subagent"):
            clean_role = target.replace("subagent.", "").replace("subagent_", "")
            config.subagents[clean_role] = voice_profile
        else:
            config.agents[target] = voice_profile

        # Update assigned agents in profile
        if target not in profile.assigned_agents:
            profile.assigned_agents.append(target)
            self.save_cloned_profile(profile)

        save_config(config)
        return target, profile.id
