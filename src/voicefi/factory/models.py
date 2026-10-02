"""
voicefi/factory/models.py
Data structures and enumerations for the Autonomous Content Creation Factory.
"""

from __future__ import annotations

import enum
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    SCRIPTING = "SCRIPTING"
    AUDIO_GEN = "AUDIO_GEN"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ContentType(str, enum.Enum):
    REEL_9_16 = "reel_9_16"
    DIALOGUE = "dialogue"
    SOLO_MONOLOGUE = "solo_monologue"
    RAP_BATTLE = "rap_battle"
    AUDIO_MEMO = "audio_memo"


@dataclass
class ScriptDialogueTurn:
    speaker: str
    text: str
    emotion: Optional[str] = None
    voice_id: Optional[str] = None
    speed: Optional[str] = None
    pause_after_ms: int = 250
    audio_path: Optional[str] = None
    duration_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ContentManifest:
    title: str
    content_type: str = ContentType.REEL_9_16.value
    target_duration_s: float = 30.0
    aspect_ratio: str = "9:16"
    turns: List[ScriptDialogueTurn] = field(default_factory=list)
    backing_track: Optional[str] = None
    background_video: Optional[str] = None
    total_words: int = 0
    calculated_duration_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content_type": self.content_type,
            "target_duration_s": self.target_duration_s,
            "aspect_ratio": self.aspect_ratio,
            "turns": [turn.to_dict() for turn in self.turns],
            "backing_track": self.backing_track,
            "background_video": self.background_video,
            "total_words": self.total_words,
            "calculated_duration_s": self.calculated_duration_s,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContentManifest:
        cast_voices = {}
        for c in data.get("cast", []):
            if "character" in c and "voice" in c:
                cast_voices[c["character"]] = c["voice"]

        turns = []
        if "turns" in data:
            for t in data["turns"]:
                if isinstance(t, dict):
                    turns.append(ScriptDialogueTurn(**t))
                elif isinstance(t, ScriptDialogueTurn):
                    turns.append(t)
        elif "slides" in data:
            for s in data["slides"]:
                spk = s.get("speaker", "Viv")
                raw_text = s.get("hook", "")
                # Clean quotation marks for natural speech delivery
                clean_text = raw_text.replace("“", "").replace("”", "").replace('"', '').strip()
                turns.append(
                    ScriptDialogueTurn(
                        speaker=spk,
                        text=clean_text,
                        emotion=s.get("emotion"),
                        voice_id=cast_voices.get(spk),
                        duration_s=float(s.get("dur", 0.0)),
                    )
                )

        total_words = int(data.get("total_words", sum(len(t.text.split()) for t in turns)))
        calc_dur = float(data.get("duration_seconds") or data.get("calculated_duration_s") or (total_words / 2.5))
        backing = data.get("backing_track")
        if not backing and isinstance(data.get("audio"), dict):
            backing = data["audio"].get("backing_track")

        if isinstance(backing, dict):
            backing = backing.get("fallback_file") or backing.get("primary_file") or backing.get("recommendation")

        return cls(
            title=data.get("title", "Untitled Content"),
            content_type=data.get("content_type", ContentType.REEL_9_16.value),
            target_duration_s=float(data.get("duration_seconds", data.get("target_duration_s", 30.0))),
            aspect_ratio=data.get("aspect_ratio", "9:16"),
            turns=turns,
            backing_track=backing,
            background_video=data.get("background_video"),
            total_words=total_words,
            calculated_duration_s=calc_dur,
        )


@dataclass
class ContentJob:
    id: Optional[int] = None
    batch_name: str = "default"
    title: str = ""
    prompt: str = ""
    content_type: str = ContentType.REEL_9_16.value
    characters: List[str] = field(default_factory=lambda: ["Viv", "Stefan"])
    target_duration_s: float = 30.0
    priority: int = 10
    status: str = JobStatus.QUEUED.value
    current_stage: str = "PENDING"
    worker_id: Optional[str] = None
    manifest_data: Optional[Dict[str, Any]] = None
    output_audio_path: Optional[str] = None
    output_video_path: Optional[str] = None
    local_tokens_saved: int = 0
    generation_seconds: float = 0.0
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d
