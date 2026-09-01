# VoiceFi™ Social Reels Production Catalog & Release Log

Master registry of compiled social reels, acoustic benchmarks, video canvas assets, and typography configurations.

---

## Master Catalog

| ID | Title | Format | Runtime | Cast / Voices | Visual Canvas Style | Status | Master Output |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REEL-008** | **10.skills (Make It Known)** | **9:16 Vertical** | **145.5s (2:25.5)** | **Jake (Lead Vocals & Performance) + Claude (Terracotta Coral) + Antigravity (Electric Cyan)** | **Full-Bleed Edge-to-Edge Split Screen + 17-Scene Spicewood Colorado River Visual Storyboard** | **MASTERED & APPROVED** | `assets/reels/reel_008_10_skills_9_16.mp4` |
| **REEL-006** | **The Speed Listening Challenge** | **9:16 Vertical** | **35.0s** | **Jake (Real Voice) + Viv (400 WPM & 600 WPM Turbo)** | **2D Pencil Flipbook + Live Speedometer Dial** | **MASTERED & APPROVED** | `assets/reels/reel_006_speed_listening_9_16.mp4` |
| **REEL-005** | **The Glass Wall (400 WPM Brain)** | **9:16 Vertical** | **37.1s** | **Jake (Real Voice) + Viv + Stefan + Christopher + Emily** | **2D Pencil Flipbook + True-Sync Kinetic Karaoke** | **MASTERED & APPROVED** | `assets/reels/reel_005_the_glass_wall_9_16.mp4` |
| **REEL-004** | **How We Built VoiceFi (Hybrid Master)** | **9:16 Vertical** | **50.4s** | **Jake (Real Voice) + Viv + Steffan + Christopher + Emily** | **2D Pencil Flipbook + VoiceFi Logo + True-Sync Kinetic Karaoke** | **MASTERED & APPROVED** | `assets/hybrid_how_we_built_voicefi_reel_9_16.mp4` |
| **REEL-003** | **How We Built VoiceFi (True Word Karaoke)** | 9:16 Vertical | 48.0s | Viv + Steffan + Christopher + Emily | 2D Hand-drawn Graphite Pencil Sketchbook | ARCHIVED | `assets/how_we_built_voicefi_true_karaoke_9_16.mp4` |
| **REEL-002** | **How We Built VoiceFi (Flipbook Video)** | 9:16 Vertical | 48.0s | Viv + Steffan + Christopher + Emily | 2D Hand-drawn Graphite Pencil Animation | ARCHIVED | `assets/how_we_built_voicefi_flipbook_reel_9_16.mp4` |
| **REEL-001** | **How We Built VoiceFi (Dynamic Island Audio)** | 9:16 Vertical | 48.0s | Viv + Steffan + Christopher + Emily | Dynamic Island Frosted Glass HUD Canvas | ARCHIVED | `assets/how_we_built_voicefi_reel_9_16.mp4` |

---

## REEL-008 Production Specification

* **Title:** `10.skills by vifi` (*Make It Known*)
* **Concept:** High-energy, laid-back hip-hop anthem detailing all 10 VoiceFi repository skills (`active-listening`, `ambient-listener`, `cross-agent-bridge`, `reel-scriptwriter`, `remote-companion`, `social-reel-producer`, `speed-talking`, `voice-memo-buffer`, `voice-persona`, `voicefi-speak`). Features creator Jake's live vocal performance synchronized frame-accurately with a 17-scene Texas Hill Country visual journey on the Colorado River in Spicewood, Texas.
* **Aspect Ratio:** 9:16 Vertical Full-Bleed (1080x1920) @ 30fps BT.709.
* **Canvas Style:** Full-bleed edge-to-edge split screen (Top: 1080x960 17-scene AI storyboard; Bottom: 1080x960 live Photo Booth webcam performance; Middle: Subtle glass badge `10.skills by vifi` at `y=935`).
* **Total Runtime:** 145.526 seconds (2:25.5).
* **Music & Audio:** Backing track "Cruisin" by Pacific (62.0 BPM in Eb Minor) + GarageBand native master vocal track (compression, auto-tune, plate reverb, stereo mastering).
* **Sync Offset:** `19.191s` vocal waveform alignment via `scipy.signal.correlate`.
* **Timing Math:** Sliced into exact `7.742s` (2-measure) blocks locked to Beat 1 on the 62.0 BPM musical grid.
* **Master Outputs:**
  * `assets/reels/reel_008_10_skills_9_16.mp4` (168 MB uncompressed master)
  * `src/voicefi/companion/static/downloads/reel_008_10_skills_9_16.mp4` (Local companion asset)
  * `marketing/social/10_skills_by_vifi.mp4` (Production master)
  * `voicefi.org/downloads/reel_008_10_skills_9_16.mp4` (23.7 MB Cloudflare global web asset)

---

### REEL-008 17-Scene Beat-Locked Storyboard Sequence (62.0 BPM Grid)

| Slot | Measure Range | Time Range | Duration | Scene Description & Action | Visual Asset |
| :---: | :---: | :---: | :---: | :--- | :--- |
| **01** | Bars 1–4 | `0.00s – 15.48s` | 15.48s | **Intro Album Slide:** Hi-res "Cruisin" by Pacific cover art with subtle zoom | `cruisin_pacific_thumbnail.jpg` |
| **02** | Bars 5–6 | `15.48s – 23.23s` | 7.74s | **Chorus 1 Drop:** Jake walking in place while background morphs through tech settings | `Man_walking_through_morphing_bac…` |
| **03** | Bars 7–8 | `23.23s – 30.97s` | 7.74s | **Dock Walk:** Jake walking along the wooden boat dock on the Colorado River in Spicewood | `Man_walking_on_boat_dock…` |
| **04** | Bars 9–10 | `30.97s – 38.71s` | 7.74s | **Dock Listen:** Jake sitting on the dock listening through wireless headphones | `Man_listening_to_music_1080p…` |
| **05** | Bars 11–12 | `38.71s – 46.45s` | 7.74s | **Holographic Phone:** Futuristic smartphone floating with holographic code and waveforms | `Smartphone_displaying_holographi…` |
| **06** | Bars 13–14 | `46.45s – 54.19s` | 7.74s | **Verse 1 Start:** Glowing cyan and orange soundwaves pulsing across river water | `Soundwaves_pulsing_on_river_water…` |
| **07** | Bars 15–16 | `54.19s – 61.94s` | 7.74s | **FPV Drone Sweep:** Dynamic low-altitude drone sweeping down the Colorado River canyon | `FPV_drone_sweeping_Colorado_River…` |
| **08** | Bars 17–18 | `61.94s – 69.68s` | 7.74s | **AI Pair Collab:** Man on dock working hands-free while home laptop compiles in PIP window | `Man_speaking_with_holographic_AI…` |
| **09** | Bars 19–20 | `69.68s – 77.42s` | 7.74s | **Dock Clapping:** Jake clapping rhythmically on the wooden dock to the snare beat | `Man_clapping_on_wooden_dock…` |
| **10** | Bars 21–22 | `77.42s – 85.16s` | 7.74s | **Chorus 2 Drop:** Energetic dock 2-step dance overlooking limestone cliffs | `Man_dancing_on_boat_dock…` |
| **11** | Bars 23–24 | `85.16s – 92.90s` | 7.74s | **Beach Sand Dance:** Dancing barefoot on the lakeside beach sandy shoreline | `Man_dance_on_sandy_shoreline…` |
| **12** | Bars 25–26 | `92.90s – 100.65s` | 7.74s | **Avatar Dance (Take 1):** Jake dancing alongside Coral Claude & Cyan Antigravity glowing avatars | `Man_dancing_with_holographic_fig… (1)` |
| **13** | Bars 27–28 | `100.65s – 108.39s` | 7.74s | **Avatar Dance (Take 2):** Close-up synchronized grooves with Coral & Cyan AI avatars | `Man_dancing_with_holographic_fig… (2)` |
| **14** | Bars 29–30 | `108.39s – 116.13s` | 7.74s | **Chrome Mic Shockwave:** High-end chrome studio mic hovering over water emitting sonic waves | `Microphone_hovering_above_water_1080p…` |
| **15** | Bars 31–32 | `116.13s – 123.87s` | 7.74s | **Seamless Continuous Zoom-Out:** Camera starts in cockpit with Jake driving speedboat + Coral Claude & Cyan Antigravity sitting behind, then smoothly flies backwards and upwards into high sky view | `Initial_Scene_-_2026-09-01_202609011341.mp4` |
| **16** | Bars 33–34 | `123.87s – 131.61s` | 7.74s | **Sunset Dock Wind-Down:** Jake sitting peacefully on the dock soaking in the sunset | `Man_listening_to_music_1080p…` |
| **17** | Bars 35–38 | `131.61s – 145.53s` | 13.91s | **Twilight Hills Outro:** Wide cinematic view of Texas Hill Country river at dusk with 3.0s smooth fade to black | `Colorado_River_hills_at_twilight…` |

---

---

## REEL-005 Production Specification

* **Concept:** "The Glass Wall · The 400 WPM Brain" — Creator Jake kicks off with the core premise of human thought velocity vs keyboard bottleneck, handing off to affirmative, high-energy agent personas (Viv on remote companion, Stefan on spoken voice evolution, Christopher on Cursor workflow velocity, and Emily on breaking through the glass wall).
* **Canvas Style:** 2D hand-drawn graphite pencil flipbook animation (12fps line boil) on textured cream parchment paper.
* **Aspect Ratio:** 9:16 Vertical (1080x1920) @ 24fps.
* **Total Runtime:** 37.08 seconds.
* **Audio Track:** 44.1kHz Stereo (Master Dialogue + Restored Creator Vocal + Procedural NumPy Lo-Fi Bed with -75% Live RMS Voice Ducking and 2.5s outro fade).
* **Subtitle Engine:** Playwright transparent kinetic batch overlay with Faster-Whisper forced word-level alignment.
* **Layout Standard:**
  * Top Speaker Pill: `position: absolute; top: 130px; left: 50%; transform: translateX(-50%)`
  * Bottom Quotes Card: `position: absolute; bottom: 160px; left: 60px; width: 960px; height: 320px`
  * Zero-Jitter Text Spans: Words transition in-place from upcoming (low opacity) -> active (glow scale) -> spoken (solid white).
  * Video Freeze-Hold: `tpad=stop_mode=clone:stop_duration=25` (full 8s video playback + 2.5s stationary logo hold).

---

### REEL-005 Turn Breakdown & Ground Truth Alignment

1. **Turn 0 (0.00s – 5.69s): Jake (Creator · Developer)**
   * **Voice:** Real human voice note (`assets/reels/reel_005/jake_intro_clean.wav`).
   * **Badge & Glow:** Olive Green (`#8B9A46`).
   * **Video Clip:** `clip_0_jake.mp4` (Human developer gesturing at typewriter keyboard with 400 WPM idea cloud).
   * **Spoken Quote:** *"Your brain thinks at 400 words a minute. Why are you choking it through a 60 word per minute keyboard?"*

2. **Turn 1 (5.87s – 11.01s): Viv (Google Antigravity Main Planner)**
   * **Voice:** `en-US-AvaNeural` (-2% rate, +0Hz pitch).
   * **Badge & Glow:** Electric Blue (`#3186FF`).
   * **Video Clip:** `clip_1_viv.mp4` (Dynamic scene walking down city street while pocketing phone).
   * **Spoken Quote:** *"Your whole dev team lives in your pocket now! Talk to us on your phone from anywhere!"*

3. **Turn 2 (11.19s – 19.23s): Stefan (Claude Code Architect)**
   * **Voice:** `en-US-SteffanNeural` (-2% rate, -1Hz pitch).
   * **Badge & Glow:** Claude Terracotta (`#D97757`).
   * **Video Clip:** `clip_2_stefan.mp4` (African American engineer in turtleneck and wire glasses pushing glasses up nose).
   * **Spoken Quote:** *"The QWERTY keyboard is 150 years old. Spoken voice has been in your DNA for 200,000 years."*

4. **Turn 3 (19.41s – 27.14s): Christopher (Cursor IDE Architect)**
   * **Voice:** `en-US-ChristopherNeural` (-2% rate, -1Hz pitch).
   * **Badge & Glow:** Cursor Cyan (`#00E5FF`).
   * **Video Clip:** `clip_3_christopher.mp4` (AI engineer pacing and gesturing at glowing holographic code IDE blocks).
   * **Spoken Quote:** *"Stand up. Pace the room. Speak your thoughts into the air—we'll handle the git commits."*

5. **Turn 4 (27.32s – 37.08s): Emily (VoiceFi Host & Closer)**
   * **Voice:** `en-IE-EmilyNeural` (Phonetic "voice fye dot org", -2% rate).
   * **Badge & Glow:** Emerald Green (`#10B981`).
   * **Video Clip:** `clip_4_emily.mp4` (Host sketching VoiceFi logo + 2.5s stationary logo freeze hold).
   * **Spoken Quote:** *"Break through the glass wall. Free your voice at voicefi.org."*

---

## REEL-004 Production Specification

* **Concept:** Definitive origin story of VoiceFi featuring creator Jake's real voice recording seamlessly handing off to autonomous AI agent dialogue (Viv, Steffan, Christopher, Emily).
* **Canvas Style:** 2D hand-drawn graphite pencil flipbook animation (12fps line boil) on textured cream parchment paper.
* **Aspect Ratio:** 9:16 Vertical (1080x1920) @ 24fps.
* **Total Runtime:** 50.47 seconds.
* **Audio Track:** 44.1kHz Stereo (Master Dialogue + SFX + Procedural NumPy Lo-Fi Bed with -75% Live RMS Voice Ducking).
* **Subtitle Engine:** Headless Chrome transparent batch overlay with sub-10ms Faster-Whisper forced alignment.
* **Layout Standard:**
  * Top Speaker Pill: `position: absolute; top: 130px; left: 50%; transform: translateX(-50%)`
  * Bottom Quotes Card: `position: absolute; bottom: 160px; left: 60px; width: 960px; height: 280px`
  * Quotes Only (clean, distraction-free aesthetic).
  * Video Freeze-Hold: `tpad=stop_mode=clone:stop_duration=25` (zero video loops).

---

### Turn Breakdown & Ground Truth Alignment
1. **Turn 0 (0.00s – 7.87s): Jake (Creator · Developer)**  
   * **Voice:** Real human voice note (`assets/jake_intro_clean.wav`).  
   * **Badge & Glow:** Olive Green (`#8B9A46`).  
   * **Video Clip:** `clip_0_jake_intro.mp4` (Developer sketching & waving with idea lightbulb).  
   * **Spoken Quote:** *"What happens when you give Google Antigravity and Claude Code a real voice? Let's ask them."*  

2. **Turn 1 (7.87s – 13.37s): Viv (Antigravity Main Planner)**  
   * **Voice:** `en-US-AvaNeural` (-2% rate).  
   * **Badge & Glow:** Electric Blue (`#3186FF`).  
   * **Video Clip:** `clip_1_cursor.mp4` (Blinking terminal cursor drawing into an AI face).  
   * **Spoken Quote:** *"Jake got so tired of silent terminals that he built VoiceFi just so we could talk back!"*  

3. **Turn 2 (13.37s – 20.11s): Steffan (Claude Code Architect)**  
   * **Voice:** `en-US-SteffanNeural` (-2% rate, -1Hz pitch).  
   * **Badge & Glow:** Claude Terracotta (`#D97757`).  
   * **Video Clip:** `clip_2_split.mp4` (Split-screen sketches debating cross-agent PRs).  
   * **Spoken Quote:** *"And by talk back, Viv means he built a cross-agent bridge so we could roast each other's pull requests."*  

4. **Turn 3 (20.11s – 28.34s): Christopher (Acoustic DSP Lead)**  
   * **Voice:** `en-US-ChristopherNeural` (-2% rate, -1Hz pitch).  
   * **Badge & Glow:** Amber Gold (`#F59E0B`).  
   * **Video Clip:** `clip_3_eraser.mp4` (Giant pencil eraser wiping soundwaves on sub-150ms barge-in).  
   * **Spoken Quote:** *"Don't forget sub-150 millisecond barge-in. One word from Jake, and our audio stops instantly."*  

5. **Turn 4 (28.34s – 36.89s): Viv (Punchline Turn)**  
   * **Voice:** `en-US-AvaNeural` + `[sfx: drum smash]`.  
   * **Badge & Glow:** Punchline Red (`#FF2A2A`).  
   * **Video Clip:** `clip_4_button.mp4` (Viv tossing the comically long 10-foot code scroll over her shoulder).  
   * **Spoken Quote:** *"Which is great, because Steffan wrote an essay on Unix sockets! But hey—we built VoiceFi using VoiceFi! 🥁"*  

6. **Turn 5 (36.89s – 50.47s): Emily (Outro & Call-to-Action)**  
   * **Voice:** `en-IE-EmilyNeural` (Phonetic "Voice-Fye").  
   * **Badge & Glow:** Emerald Green (`#10B981`).  
   * **Video Clip:** `clip_5_flipbook.mp4` (Artist sketching the official VoiceFi beacon logo & URL).  
   * **Spoken Quote:** *"Stop typing into the void. Build with your AI team in real-time voice. VoiceFi — Free your voice at voicefi.org."*  
