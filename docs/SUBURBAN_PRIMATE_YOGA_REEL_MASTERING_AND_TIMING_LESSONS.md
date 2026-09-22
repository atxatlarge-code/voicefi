# 🧘‍♂️ Suburban Primate Yoga Reel — Neural Cloning, Broadcast Silk Mastering & Timing Standards

Codified production lessons, acoustic mastering standards, and comedic documentary timing secrets established during the authoring and Picture Lock of the **Suburban Primate Documentary Broadcaster Yoga Reel** (`46.50s`, 1080x1920 9:16 vertical short).

---

## 🧬 1. The F5-TTS Static / Vocoder Fuzz Elimination Breakthrough

### The Problem Diagnosed
During initial zero-shot neural cloning with F5-TTS, raw audio stems exhibited a noticeable high-frequency "static", grain, or room fuzz throughout narration.
Spectral analysis revealed:
1. **Flow-Matching Under-Convergence**: At the default `nfe_step=16`, the ODE diffusion trajectory terminates prematurely on Apple Silicon Metal Performance Shaders (MPS), leaving residual noise in the predicted mel-spectrogram.
2. **Vocos Vocoder Ultrasonic Hash**: The Vocos neural vocoder introduces low-amplitude digital artifacts and hash in the 10.5 kHz – 12.0 kHz range, which typical studio compression amplifies into audible hiss.

### The Solution
1. **Convergence Step Elevation (`nfe_step=32`)**:
   Increasing `nfe_step` from 16 to 32 allows the flow-matching solver to fully converge. On Apple Silicon (M-series), 32 steps takes ~12–25 seconds per clause and produces a noticeably smoother, silkier vocal texture.
2. **Broadcast Silk Mastering Chain**:
   ```bash
   ffmpeg -y -i raw_diffusion_take.wav \
     -af "afftdn=nr=10:nf=-35,lowpass=f=10500,equalizer=f=6000:width_type=q:width=2.0:g=-2.0,equalizer=f=125:width_type=q:width=1.0:g=2.5,volume=-0.5dB" \
     silk_mastered_take.wav
   ```
   - **`afftdn=nr=10:nf=-35`**: Removes stationary diffusion background floor noise.
   - **`lowpass=f=10500`**: Steep cutoff of ultrasonic vocoder hash above 10.5 kHz.
   - **`equalizer=f=6000:width_type=q:width=2.0:g=-2.0`**: De-esses harsh 's' and 't' transients.
   - **`equalizer=f=125:width_type=q:width=1.0:g=2.5`**: Restores intimate chest proximity resonance.
   - **Result**: Measured background noise floor dropped by **20 dB** (from `0.0019` to `0.0002` RMS), yielding pristine, broadcast-ready British vocal silk.

---

## 🎭 2. The Documentary Broadcaster Prosody & Phrasing Rules

### The "Exclamation Mark" Trap
When synthesizing lines like *"Yet... triumph!"* or *"How profound!"*, exclamation marks (`!`) signal the neural model to apply standard American broadcast prosody: pitch spikes upward into an energetic, cheerful announcement.

The documentary broadcaster's hallmark delivery on comedic discoveries or natural triumphs is the exact opposite:
- **Tone**: A hushed, reverent, breathy whisper of awe and gravelly chest resonance.
- **Punctuation Rules**:
  - Replace `!` with `.` or `...`.
  - ❌ `"Yet... triumph! A brazen pelvic display."`
  - ✅ `"Yet... triumph. A brazen pelvic display."` (triggers deep British RP cadence)
  - ❌ `"How profound!"`
  - ✅ `"How... profound."` (triggers contemplative wonder and pitch drop into vocal fry)
- **Tempo Tuning**: Slowing down by ~8–12% (`speed=0.88 – 0.92`) allows the documentary broadcaster's characteristic dramatic pauses to resonate.

---

## 🎛️ 3. Timeline Architecture: NumPy Assembly vs. FFmpeg `amix`

### Why FFmpeg `amix=inputs=N` Fails for Dialogue Stems
When combining 7 separate dialogue acts with background music:
1. `amix` normalizes each input by `1/N`, attenuating vocal presence unless manually overridden.
2. Even more damagingly: `amix` sums the background noise floor of all inactive stems during pauses, compounding residual room tone and creating an eerie phasing flutter.

### The Pure NumPy Timeline Standard
1. **Zero-Buffer Initialization**:
   Create a single continuous 1D NumPy array for the exact timeline length (`int(round(46.50 * 24000))`).
2. **Sample-Accurate Positioning**:
   Place each trimmed voice stem at its exact target start sample (`int(round(target_start * sr))`).
3. **Edge Micro-Fades**:
   Apply 20ms linear fade-in and 40ms linear fade-out to each stem slice to ensure 0 zero-crossing clicks.
4. **Guaranteed Absolute Silence**:
   All inter-act gaps have true mathematical zero amplitude (`0.000000`), allowing the acoustic guitar and birdsong to breathe cleanly.

---

## 🌿 4. Multi-Layer Soundscape & Dynamic Ducking

A nature documentary soundscape requires organic acoustic layers working in harmony:
1. **Voice Stem**: Front and center at unity gain (`0 dB`).
2. **Acoustic Guitar Bed**: Warm fingerpicking (`natural_strum_05.mp3`) leveled at `-18 dB`.
3. **Park Ambience**: High-fidelity European blackbird birdsong loop leveled at `-24 dB`.
4. **Intelligent Sidechain Ducking**:
   ```python
   env = np.abs(voice_audio)
   kernel = np.ones(int(sr * 0.20)) / int(sr * 0.20)  # 200ms smoothing
   env_smooth = np.convolve(env, kernel, mode="same")
   duck = 1.0 - np.clip(env_smooth * 3.5, 0.0, 0.55)  # ducks guitar by up to -6 dB under voice
   ```
   Ducks the guitar bed by -6 dB whenever the documentary broadcaster speaks, then smoothly swells back up during dramatic pauses.

---

## 🎬 5. Video Freeze-Frame Hold (`tpad=stop_mode=clone`)

### The Comic Freeze-Frame Secret
In raw footage, the subject often reaches for the phone or stumbles at the end of the recording.
To achieve comedic perfection:
1. **Identify the Hero Peak**: Jake recovers from the roll-over into a smiling pelvic display arch pose at `42.5s – 43.8s`.
2. **Trim Before Phone Handling**: The hand begins reaching towards the camera lens at `43.84s`.
3. **Clone the Final Frame**:
   ```bash
   [0:v]trim=end=43.83,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=2.67,scale=1080:1920,format=yuv420p[v]
   ```
4. **The Dramatic Hold**:
   - `43.83s`: Video freezes cleanly on the triumphant pelvic smile.
   - `44.00s`: The documentary broadcaster delivers the hushed punchline: *"How... profound."*
   - `45.27s – 46.50s`: The frozen frame holds as the acoustic guitar and birds fade out gracefully.

---

## 📊 6. Master Timeline Alignment Breakdown

| Act | Time Window | Dur | Spoken Thought / Soundscape Action |
| :--- | :--- | :--- | :--- |
| **Beat 1** | `00.80s – 05.60s` | 4.80s | *"Here... in the parkland savannahs... a sacred ritual ground."* |
| **Gap** | `05.60s – 06.20s` | 0.60s | Acoustic guitar strum + blackbird call |
| **Beat 2** | `06.20s – 19.11s` | 12.91s | *"A solitary male prepares his vessel for aggressive relaxation. Vibrant crimson plumage... bearing the cryptic warning: I am You... You are Me."* |
| **Gap** | `19.11s – 19.30s` | 0.19s | Guitar bed continues |
| **Beat 3** | `19.30s – 26.78s` | 7.48s | *"He arches back to the midday sun... exposing his jugular, desperately seeking vitamin D."* |
| **Gap** | `26.78s – 27.00s` | 0.22s | Guitar bed continues |
| **Beat 4** | `27.00s – 34.79s` | 7.79s | *"Calibrating the wrists... he slips into transcendental stasis. Pure... undisturbed bliss."* |
| **Gap** | `34.79s – 35.00s` | 0.21s | Sudden tension pause as balance falters |
| **Beat 5** | `35.00s – 39.60s` | 4.60s | *"Catastrophe! The creature topples like an overturned beetle!"* |
| **Gap** | `39.60s – 39.80s` | 0.20s | Recovery motion on grass |
| **Beat 6** | `39.80s – 42.86s` | 3.06s | *"Yet... triumph. A brazen pelvic display."* |
| **Hold** | `42.86s – 43.83s` | 0.97s | Guitar groove & birds over living pelvic pose |
| **FREEZE** | `43.83s` | — | **Video locks on frozen smiling pelvic display** |
| **Beat 7** | `44.00s – 45.27s` | 1.27s | *"How... profound."* (delivered over frozen frame) |
| **Outro** | `45.27s – 46.50s` | 1.23s | Guitar & blackbird decay to silence over freeze-frame |

---

## ⏱️ 7. Music Bed Pre-Roll & Metronome Count-in Truncation

### The GarageBand "Click Click Click" Bug
Music beds exported from DAWs (like GarageBand, Logic, or Pro Tools) frequently include a 1-bar or 2-bar metronome count-in before the instrument performance begins.
In `natural_strum_05.mp3`, the metadata revealed:
```
Chapter #0:0: start 0.000000, end 2.500000 | title: Tempo: 96.0
Chapter #0:1: start 2.500000, end 115.000000 | title: ch1
```
The 4-beat click count-in ran from `0.0s` to `2.5s`, followed by decay until the guitar performance onset at `t = 3.728s`.

### The Fix
Always slice DAW-exported beds directly at the first musical transient:
```bash
ffmpeg -y -ss 3.70 -i natural_strum_05.mp3 -ar 24000 -ac 1 /tmp/guitar_bed_24k.wav
```
This guarantees an organic, immediate musical entrance with zero metronome bleed.
