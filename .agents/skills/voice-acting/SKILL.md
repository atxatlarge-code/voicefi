---
name: voice-acting
description: Directs and synthesizes high-expression local Voice Acting, character performances, theatrical delivery, and staccato cadence on Apple Silicon Metal GPU using VoiceFi's discrete codec MLX engine (Qwen3-TTS) and F5-TTS multi-emotion flow matching without cloud APIs.
---

# 🎭 Voice Acting Skill — VoiceFi™

The definitive engine and directive guide for authoring, directing, and synthesizing **Voice Acting** on Apple Silicon Metal GPU.

---

## 🎯 What is Voice Acting? (The 3 Generations of Voice AI)

VoiceFi distinguishes between three fundamental tiers of voice synthesis:

1. **Gen 1: Traditional TTS (Kokoro, StyleTTS, Apple Say, Edge TTS)**
   - Text -> Phonemes -> Spectrogram.
   - Clear and fast, but completely flat ("GPS Monotone"). Zero semantic comprehension, sarcasm, or dynamic range.
2. **Gen 2: Biometric Voice Cloning (F5-TTS Flow Matching)**
   - Replicates exact vocal timbre from a reference audio seed.
   - Emotionally locked to the acoustic energy of that seed. (A calm seed speaks yelled lines calmly).
3. **Gen 3: Voice Acting (Discrete Neural Audio Codecs / MLX Qwen3-TTS / Theatrical Director)**
   - Audio is quantized into discrete tokens. An autoregressive transformer interprets emotional subtext, breath intakes, theatrical pitch swings, and natural language performance directives (`--instruct`).
   - Runs fully local on Apple Silicon Metal GPU at **0.98x RTF** with ~3.3GB VRAM.

---

## 🏛️ The Theatrical Director (`src/voicefi/tts/director.py`)

Voice acting requires script direction before synthesis:

### 1. Staccato Cadence & Walken Directing
Walken and dramatic actors rely on unexpected pauses, mid-clause breaks, and signature lead-ins:
```python
from voicefi.tts.director import TheatricalDirector

raw = "I inspected the repository and all unit tests are passing."
directed = TheatricalDirector.direct_walken_cadence(raw)
# Output: "Guess what?... I inspected the repository and... all unit tests are passing. Beautiful."
```

### 2. Punctuation & Ellipsis Injections
- Use dramatic ellipses (`...`) for pregnant pauses.
- Use dashes (`—`) for abrupt gear shifts.
- Capitalize key words or insert bracket cues `[shouts]`, `[sighs]`, `[whispers]` when feeding through the direct prompt engine.

---

## 🎙️ Canonical Persona Presets

VoiceFi comes pre-configured with 6 theatrical character profiles in [`src/voicefi/tts/voice_acting.py`](file:///Users/jaketrigg/Projects/VoiceFi/src/voicefi/tts/voice_acting.py):

| Persona Key | Base Actor | Default Acting Directive (`--instruct`) | Character Archetype |
| :--- | :--- | :--- | :--- |
| **`drill_sergeant`** | `ryan` | *"Shouting aggressively with fierce military drill sergeant discipline, barking commands, loud projection, rapid cadence, and zero hesitation."* | Boot camp drill instructor |
| **`deadpan_ironist`** | `vivian` | *"Speaking with deadpan condescension, flat monotone smirk, weary software engineer chuckling with dry Elizabethan irony and trailing vocal fry."* | Weary senior architect |
| **`game_show_host`** | `aiden` | *"Extravagant high-energy 1980s television game-show host holding a golden microphone on stage with explosive booming showmanship and glossy enthusiasm."* | Retro TV showman |
| **`shakespearean`** | `eric` | *"Elizabethan Shakespearean classical stage actor performing a high-stakes tragedy with immense theatrical gravitas, trembling pathos, and dark poetic weight."* | Classical stage tragedian |
| **`conspiratorial_insider`** | `sohee` | *"Underground hacker whispering forbidden operating system secrets in a dimly lit alley with hushed urgent paranoia, conspiratorial intimacy, and nervous tension."* | Paranoid alleyway hacker |
| **`christopher_walken`** | `sample_cowbell_snl` | *"Idiosyncratic staccato rhythm, unexpected dramatic pauses, sudden pitch spikes, deadpan comedic intensity."* | Iconic eccentric actor |

---

## 🛠️ CLI Usage & Quick Reference

```bash
# 1. Preset Voice Acting Personas
vifi speak "Attention! Drop and give me twenty right now!" -p voice_acting -v drill_sergeant
vifi speak "If you guessed B, congratulations. You broke staging." -p voice_acting -v deadpan_ironist
vifi speak "For 500 points! What is your last resort command?" -p voice_acting -v game_show_host

# 2. Custom Theatrical Direction (--instruct)
vifi speak "Avast ye! The starboard database be taking on water!" \
  -p voice_acting \
  --instruct "Grizzled 17th-century pirate captain barking frantically in a sea storm"

# 3. Christopher Walken Turn Audition
vifi speak "Your production database... it has a fever!" -v christopher_walken
```

---

## 📦 Python SDK Usage

```python
from voicefi.tts.voice_acting import VoiceActingTTS

# 1. Initialize with preset or custom instruction
actor = VoiceActingTTS(
    persona_name="drill_sergeant",
    instruct="Shouting aggressively with fierce military discipline",
    speed=1.1,
)

# 2. Synthesize directly to broadcast-mastered WAV
actor.speak_to_file(
    "Drop and give me twenty right now!",
    "/tmp/drill_sergeant.wav"
)

# 3. Or speak aloud on macOS CoreAudio
actor.speak("Listen up recruits!")
```

---

## ⚡ Speech-to-Speech (STS) Zero-Render Video Dubbing

Because Voice Acting decouples timbre from performance, you can swap speaker identity while preserving 100% of video mouth movements:

1. Extract audio from an existing video (e.g. `interview.mp4`).
2. Run Speech-to-Speech conversion to another voice (e.g. Trump -> Walken or Obama).
3. Mux the new audio back into the original video with zero pixel re-rendering:
```bash
ffmpeg -i original.mp4 -i converted_voice.wav -c:v copy -map 0:v:0 -map 1:a:0 dubbed.mp4
```
**Advantage:** Zero blurry mouth artifacts (unlike Wav2Lip), runs in 0.3 seconds on macOS, and lips stay in 100% sync.

---

## 🎨 Authentic Character Voice Seed Recipe (The Sketch-to-Character Blueprint)

When cloning comedic or theatrical personas (e.g. Christopher Walken's *The Continental* vs *Bruce Dickinson / More Cowbell*):
* **Diffusion models inherit performance energy:** Never use flat generic interview clips or synthetic TTS samples as seeds.
* **The Rule:** The F5-TTS reference seed (`ref_audio`) must be an authentic 5-10 second clip of the actor **performing in that specific character role**.
* **Detailed Blueprint:** See [`docs/AUTHENTIC_VOICE_CHARACTER_TEMPLATE.md`](file:///Users/jaketrigg/Projects/VoiceFi/docs/AUTHENTIC_VOICE_CHARACTER_TEMPLATE.md).

```bash
# 1. Download sketch/movie source
yt-dlp -x --audio-format wav -o "/tmp/character.%(ext)s" "<URL>"

# 2. Slice 5-10s at 24kHz mono
ffmpeg -y -ss <START> -to <END> -i /tmp/character.wav -ar 24000 -ac 1 ~/.voicefi/cloned_voices/<actor>/<char>/ref_<char>.wav

# 3. Transcribe exact reference text for f5_ref_text
# 4. Synthesize with directed script cadence
```
