# VoiceFi™ Social Reels Production Catalog & Release Log

Master registry of compiled social reels, acoustic benchmarks, video canvas assets, and typography configurations.

---

## Master Catalog

| ID | Title | Format | Runtime | Cast / Voices | Visual Canvas Style | Status | Master Output |
| **SPICEWOOD-916** | **Spicewood Outlaws™ (Full Master & Social Cutdowns)** | **9:16 Vertical** | **261.4s (4:21.4) [Master] / 55.4s [Shorts] / 95.1s [Act 2] / 110.8s [Act 3]** | **vifi (Lead Vocals) + Shinra B (Beat) + King Louie Samples** | **Full-Bleed Center-Crop & Ambient Blur + 2-Line Kinetic Karaoke + Glassmorphic Title Pill + Audited Hype Bubbles** | **MASTERED & APPROVED (PICTURE LOCK)** | `~/Desktop/spicewood_outlaws_full_master_9_16.mp4` |
| **REEL-013** | **Ogygia · The Island of the Concealed** | **9:16 Vertical** | **122.2s (2:02.2)** | **The Odyssey Narrator (en-US-ChristopherNeural)** | **Minimalist Documentary Subtitles + Ken Burns Motion (Full-Bleed Photography)** | **MASTERED & APPROVED** | `assets/reels/the_odyssey/ogygia/ogygia_reel_9_16.mp4` |
| **REEL-065** | **Respect Your Elders (Retirement Age 65)** | **9:16 Vertical** | **40.0s** | **The Elder (Native Flow) + Viv (en-US-AvaNeural) + Emily (Outro)** | **Hybrid 2D Pencil Flipbook & Live Canvas + True-Sync Kinetic Karaoke** | **MASTERED & APPROVED** | `assets/reels/reel_065_respect_your_elders_9_16.mp4` |
| **REEL-008** | **10.skills (Make It Known)** | **9:16 Vertical** | **145.5s (2:25.5)** | **Jake (Lead Vocals & Performance) + Claude (Terracotta Coral) + Antigravity (Electric Cyan)** | **Full-Bleed Edge-to-Edge Split Screen + 17-Scene Spicewood Colorado River Visual Storyboard** | **MASTERED & APPROVED** | `assets/reels/reel_008_10_skills_9_16.mp4` |
| **REEL-006** | **The Speed Listening Challenge** | **9:16 Vertical** | **35.0s** | **Jake (Real Voice) + Viv (400 WPM & 600 WPM Turbo)** | **2D Pencil Flipbook + Live Speedometer Dial** | **MASTERED & APPROVED** | `assets/reels/reel_006_speed_listening_9_16.mp4` |
| **REEL-005** | **The Glass Wall (400 WPM Brain)** | **9:16 Vertical** | **37.1s** | **Jake (Real Voice) + Viv + Stefan + Christopher + Emily** | **2D Pencil Flipbook + True-Sync Kinetic Karaoke** | **MASTERED & APPROVED** | `assets/reels/reel_005_the_glass_wall_9_16.mp4` |
| **REEL-004** | **How We Built VoiceFi (Hybrid Master)** | **9:16 Vertical** | **50.4s** | **Jake (Real Voice) + Viv + Steffan + Christopher + Emily** | **2D Pencil Flipbook + VoiceFi Logo + True-Sync Kinetic Karaoke** | **MASTERED & APPROVED** | `assets/hybrid_how_we_built_voicefi_reel_9_16.mp4` |
| **REEL-003** | **How We Built VoiceFi (True Word Karaoke)** | 9:16 Vertical | 48.0s | Viv + Steffan + Christopher + Emily | 2D Hand-drawn Graphite Pencil Sketchbook | ARCHIVED | `assets/how_we_built_voicefi_true_karaoke_9_16.mp4` |
| **REEL-002** | **How We Built VoiceFi (Flipbook Video)** | 9:16 Vertical | 48.0s | Viv + Steffan + Christopher + Emily | 2D Hand-drawn Graphite Pencil Animation | ARCHIVED | `assets/how_we_built_voicefi_flipbook_reel_9_16.mp4` |
| **REEL-001** | **How We Built VoiceFi (Dynamic Island Audio)** | 9:16 Vertical | 48.0s | Viv + Steffan + Christopher + Emily | Dynamic Island Frosted Glass HUD Canvas | ARCHIVED | `assets/how_we_built_voicefi_reel_9_16.mp4` |

---

## SPICEWOOD-916 Production Specification

* **Title:** `Spicewood Outlaws™ · The Cultural Anthem & Music Video (Full Master & Social Cutdowns)`
* **Artist & Credits:** vifi (Lead Vocals) · Instrumental: *"Society"* (Prod. Shinra B) · 85.0 BPM Boom Bap.
* **Canvas Style:** Dynamic 9:16 Vertical (1080x1920) adapting 16:9 widescreen footage using intelligent per-shot rules:
  * **Center-Crop (`center`):** Close-ups, truck power slides, money fan, whittling, and action sequences.
  * **Ambient Blur (`ambient_blur`):** Hill Country panoramas, Krause Springs waterfall, Pedernales rapids, and sunset vistas.
* **Aspect Ratio:** 9:16 Vertical Full HD (`1080x1920`) @ 24fps, H.264 High Profile (`crf 18`, `g=24`, `faststart`).
* **Total Runtime:** 
  * Full Master: **261.39s (04:21.39)**
  * YouTube Shorts Cutdown (Act 1): **55.38s** (<60s hard limit)
  * TikTok / Reels Speedburst (Act 2): **95.08s**
  * Bonfire Climax Finale (Act 3): **110.83s**
* **Audio Engineering:** 
  * Pristine 44.1kHz 320 kbps AAC mastered directly from uncompressed 24-bit PCM master vocal mix (`normalize=0`).
  * **Instant 0.00s Zero-Black-Frame Start:** Extracted clean video-only streams before concatenation, stripping chapter markers (`-map_chapters -1`) and eliminating container priming offsets (mean brightness `101.1` at `0.00s`).
  * **Frame-Accurate Diegetic Needle Drop (`t = 2.45s`):** `NeedleDrop02.mp3` delayed with `adelay=2100|2100` so the mechanical impact transient strikes with a punchy thump (`rms = 7295.2`, `peak = 22576`, `-0.6 dBTP`) matching the exact video frame (Frames 16–17, `y = 399`) where the stylus makes contact with the spinning vinyl grooves.
* **Typography & Safe-Zone Graphics:**
  * **Modern Floating Glassmorphic Title Pill (`y = 180`, `1.00s – 5.00s`):** Translucent frosted badge (`fill=(14, 16, 22, 215)`, Texas Amber border `(245, 158, 11, 90)`), micro-groove vinyl disc icon, bold title (`SPICEWOOD OUTLAWS`), and credits (`VIFI • BEAT: "SOCIETY" BY SHINRA B`).
  * **2-Line Comma-Split Kinetic Subtitles (`y = 1380 – 1460`):** Subtitles cleanly break onto line 2 after commas before bold rhyming punchlines. Real-time spoken word highlighting in Texas Amber Gold (`#F59E0B`).
  * **Audited Comic Hype Bubbles (`y = 460 – 540`):** Micro-calibrated acoustic speech alignment across all 11 ad-lib bursts:
    * `...grotto...` (`15.15s – 15.55s`): Whispered echo only; clears before *"I'M SO HOT THOUGH"*.
    * `Rarw` (`16.65s – 17.00s`): Slotted in the pocket between *"THOUGH"* and *"Cold spring water"*.
    * `hubba hubba` (`19.30s – 19.85s`): Enters on female ad-lib; clears before *"Pedernales"*.
    * `ding ding` (`20.60s – 21.15s`): Synchronized to chimes; clears before *"COLORADO"*.
    * `Rio Grande!` (`22.35s – 22.95s`): Locked over shouted ad-lib (resolved previous premature cutoff).
    * `Gold, baby!` (`27.58s – 28.20s`): Enters on *"Gold"* and holds through *"baby!"*.
    * `Right now!` (`30.55s – 30.95s`): Slotted on Bar 11 turnaround cue.
    * `Ride out!` (`33.15s – 33.55s`): Slotted on horse gallop reveal following *"LIKE TONTO"*.
    * `Talk to 'em Louie` (`46.50s – 48.35s`): Spans King Louie brass swell to Bar 18 downbeat.
    * `pew pew` (`Act 3, 13.80s – 14.45s`): Snare hit impact following *"GUNS ABLAZE!"*.
    * `t-t-tik tok tik` (`Act 3, 26.60s – 27.94s`): Enters on stutter *"t-t-tik"* at 26.60s.
* **Deliverables:**
  * Full Master 9:16: `~/Desktop/spicewood_outlaws_full_master_9_16.mp4` (341.6 MB)
  * YouTube Shorts Cutdown: `~/Desktop/spicewood_shorts_act1_55s.mp4` (57.1 MB)
  * TikTok / Reels Speedburst: `~/Desktop/spicewood_reel_act2_speedburst.mp4` (99.0 MB)
  * Bonfire Climax Finale: `~/Desktop/spicewood_reel_act3_finale.mp4` (185.4 MB)
  * Companion PWA Downloads: `src/voicefi/companion/static/downloads/`

---

## REEL-013 Production Specification

* **Title:** `Ogygia · The Island of the Concealed` (REEL-013)
* **Concept:** Mythological documentary memoir tracing the synchronicity of Homer’s *Odyssey* in Jake Trigg’s 6-year transformation. On Aug 6, 2022, boarding a flight to his first plant medicine ceremony, the Austin Airport digital gate inexplicably displayed "Destination: Ogygia." The film traces the sanctuary of Ogygia—deep rites of passage, exploring spirituality, community, and the divine feminine following an undiagnosed 2020 car collision and silent TBI—and the bronze axe of manual labor (105° Texas heat, UPS midnight shifts, 300 job rejections) that grounded the spirit, leading to the triumphant homecoming through 1,375 commits and the founding of VoiceFi™.
* **Canvas Style:** High-resolution documentary photography with Ken Burns dynamic motion (slow push-in, vertical glides, landscape blur-fill canvas) + clean minimalist documentary subtitles (Option A: centered, translucent pill backing, 1-2 lines max) letting personal photos breathe full-bleed.
* **Aspect Ratio:** 9:16 Vertical Full HD (1080x1920) @ 30fps BT.709.
* **Total Runtime:** 122.2 seconds (2:02.2 / 14 scenes).
* **Audio Profile:** 44.1kHz Stereo (Master Narration via `en-US-ChristopherNeural` + Procedural NumPy Ambient Bed in D Minor with Sub-Bass Heartbeat Pulse, Ocean Foam Pink Noise, -75% Live RMS Voice Ducking, and 3.5s Outro Fade).
* **Layout Standard:**
  * Clean Minimalist Subtitles: `bottom: 180px`, `max-width: 900px`, 46px Arial Bold with sleek translucent dark pill backing (`rgba(0,0,0,0.55)`).
  * Full-Bleed Imagery: Top Dynamic Island HUD, slide counter badges, and giant frosted quote boxes removed to prevent visual clutter and let original photos breathe.
* **Master Outputs:**
  * `assets/reels/the_odyssey/ogygia/ogygia_reel_9_16.mp4` (Master 1080x1920 vertical video)
  * `src/voicefi/companion/static/downloads/ogygia_reel_9_16.mp4` (Mobile Companion Downloads Hub)
  * `assets/reels/the_odyssey/ogygia/ogygia_reel_master_audio.mp3` (Master stereo audio track)
  * `marketing/social/reels/013_ogygia_island_of_the_concealed.json` (Declarative manifest)
  * `marketing/social/reels/ogygia_island_of_the_concealed.md` (Visual storyboard & script)

---

## REEL-065 Production Specification

* **Title:** `Respect Your Elders · The Retirement Age Voice Revolution` (REEL-065)
* **Concept:** Industry satire celebrating retirement age 65 and the power of spoken voice. The Seasoned Builder Eric (raised doing deals over the telephone without typing) discovers VoiceFi, realizing an entire generation of Boomers is about to run circles around tech because voice is 3x faster than typing. Viv demonstrates hands-free code execution, spreadsheets, and clicks, followed by Emily's closing call to action.
* **Canvas Style:** Hybrid 2D architectural pencil sketch background + realistic characters inside mechanical floating orbs with glowing cyan waveforms, checkmarks, and floating spreadsheets.
* **Aspect Ratio:** 9:16 Vertical Full HD (1080x1920) @ 24fps.
* **Total Runtime:** 40.00 seconds (5 scenes × 8.0s).
* **Audio Track:** 44.1kHz Stereo (Master Dialogue + Native Google Flow Dialogue + Procedural NumPy Lo-Fi Bed with -75% Live RMS Voice Ducking and 2.5s outro fade).
* **Subtitle Engine:** Playwright transparent kinetic batch overlay with Faster-Whisper forced word-level alignment.
* **Layout Standard:**
  * Top Speaker Pill: `position: absolute; top: 130px; left: 50%; transform: translateX(-50%)`
  * Bottom Quotes Card: `position: absolute; bottom: 160px; left: 60px; width: 960px; height: 320px`
  * Zero-Jitter Text Spans: Words transition in-place from upcoming (low opacity) -> active (glow scale) -> spoken (solid white).
  * Video Freeze-Hold: `tpad=stop_mode=clone:stop_duration=25` (smooth continuous playback).
* **Optimization (Zero Mac Freezing):**
  * `os.nice(15)` background priority keeps macOS UI, mouse, keyboard, and display 100% fluid.
  * Fast-path rendering with `-threads 4` and `-preset ultrafast -crf 20`.
* **Master Outputs:**
  * `assets/reels/reel_065_respect_your_elders_9_16.mp4` (Master 1080x1920 video)
  * `src/voicefi/companion/static/downloads/reel_065_respect_your_elders_9_16.mp4` (Companion Downloads Hub)
  * `assets/reel_065_respect_your_elders_master.mp3` (Master mixed audio track)

---

### REEL-065 Turn Breakdown & Ground Truth Alignment

1. **Turn 0 (0.00s – 8.00s): Eric (40 Years on the Phone)**
   * **Voice:** Native Google Flow character audio (authentic laugh & rotary phone delivery).
   * **Badge & Glow:** Amber Gold (`#F59E0B`).
   * **Video Clip:** `clip_0_eric.mp4` (Eric gesturing with vintage telephone inside mechanical floating orb).
   * **Spoken Quote:** *"Respect your elders. You know who was raised talking to people instead of typing? My generation."*

2. **Turn 1 (8.00s – 16.00s): Viv (Antigravity Main Planner)**
   * **Voice:** Native Google Flow character audio (100% frame-accurate lip sync, natural conversational pause & smile).
   * **Badge & Glow:** Electric Blue (`#3186FF`).
   * **Video Clip:** `clip_1_viv.mp4` (Viv inside glowing orb explaining VoiceFi giving AI agents ears).
   * **Spoken Quote:** *"And you were right, Eric! VoiceFi gave us ears so you can talk to computers now."*

3. **Turn 2 (16.00s – 24.00s): Eric (40 Years on the Phone)**
   * **Voice:** Native Google Flow character audio (boisterous laughter & phone handset delivery).
   * **Badge & Glow:** Amber Gold (`#F59E0B`).
   * **Video Clip:** `clip_2_eric.mp4` (Eric laughing heartily about an army of Boomers running circles around tech).
   * **Spoken Quote:** *"Wait until my friends get ahold of this. There's going to be a whole army of Boomers running circles around tech because they can just talk to it."*

4. **Turn 3 (24.00s – 32.00s): Viv (Background AI Subagents)**
   * **Voice:** Native Google Flow character audio (natural cadence matching code execution & spreadsheet gestures).
   * **Badge & Glow:** Electric Blue (`#3186FF`).
   * **Video Clip:** `clip_3_viv.mp4` (Viv gesturing at glowing cyan waveforms and floating spreadsheets).
   * **Spoken Quote:** *"Tell me what to build, and I'll execute the code, export the spreadsheets, and handle the clicks silently."*

5. **Turn 4 (32.00s – 40.00s): Emily (VoiceFi Closer)**
   * **Voice:** `en-IE-EmilyNeural` (-2% rate, +0Hz pitch, 1.20s natural lead-in offset).
   * **Badge & Glow:** Emerald Green (`#10B981`).
   * **Video Clip:** `clip_4_emily.mp4` (Cute animated microphone robot mascot and illuminated smartphone).
   * **Spoken Quote:** *"Talking is just faster. Free your voice at voicefi.org."*

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
