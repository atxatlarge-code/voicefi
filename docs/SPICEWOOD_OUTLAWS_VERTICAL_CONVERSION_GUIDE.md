# Spicewood Outlaws™ — Vertical 9:16 Conversion & Social Distribution Guide

**Universal 9:16 Vertical Video Architecture for TikTok, Instagram Reels, YouTube Shorts, and VoiceFi Mobile Companion PWA**

---

## 🎬 Executive Summary

The official music video and cultural anthem **"Spicewood Outlaws™"** by **vifi** (4m 21.44s, 85.0 BPM Boom Bap) has been systematically adapted from 16:9 widescreen landscape (`1280x720`) into full-resolution **9:16 vertical (`1080x1920`)**.

This document details the aesthetic, typographic, acoustic, and platform-specific engineering standards implemented to maximize engagement, retention, and viral reach across short-form mobile video algorithms.

---

## 📦 Master & Modular Deliverables Inventory

All video masters are encoded at `1080x1920`, 24.0 fps, `yuv420p`, keyframe interval `g=24, keyint_min=12`, with `+faststart` moov atoms for instant 0ms mobile playback. Audio is mastered to 44.1kHz 320 kbps AAC directly from the uncompressed 24-bit PCM master vocal mix (`-0.1 dBTP`, `-12.1 LUFS`).

| Deliverable | Duration | Size | Platform Target | Primary Location |
| :--- | :--- | :--- | :--- | :--- |
| **Spicewood Outlaws™ Full Master 9:16** | **04:21.39** | 341.6 MB | YouTube / PWA / Long-Form Reels | `~/Desktop/spicewood_outlaws_full_master_9_16.mp4` |
| **YouTube Shorts Cut (Act 1)** | **00:55.38** | 57.3 MB | **YouTube Shorts** (<60s Hard Limit) | `~/Desktop/spicewood_shorts_act1_55s.mp4` |
| **TikTok / IG Reels Speedburst (Act 2)** | **01:35.08** | 99.0 MB | **TikTok & IG Reels** High-Octane | `~/Desktop/spicewood_reel_act2_speedburst.mp4` |
| **Bonfire Climax Finale (Act 3)** | **01:50.83** | 185.5 MB | **TikTok / IG Reels / Threads** Finale | `~/Desktop/spicewood_reel_act3_finale.mp4` |
| **Act 1 Master Vertical** | **00:55.38** | 57.3 MB | Companion PWA / Modular Archive | `src/voicefi/companion/static/downloads/` |
| **Act 2 Master Vertical** | **01:35.08** | 99.0 MB | Companion PWA / Modular Archive | `src/voicefi/companion/static/downloads/` |
| **Act 3 Master Vertical** | **01:50.83** | 185.5 MB | Companion PWA / Modular Archive | `src/voicefi/companion/static/downloads/` |

---

## 📐 Per-Shot Framing Rules (1080x1920)

Rather than applying a uniform crop across the entire film, each shot was individually audited and assigned one of two tailored visual treatments:

### 1. Full-Bleed Center-Crop (`center`)
- **Use Case:** Human characters, close-ups, cars, action sequences, drift trucks, and whittling.
- **Implementation:** Scales source footage to 1920px height (`scale=1080:1920:force_original_aspect_ratio=increase`), extracts the center `(in_w-1080)/2`, and sets strict SAR 1:1.
- **Result:** Fills 100% of modern phone displays edge-to-edge without letterboxing.

### 2. Ambient Blurred Landscape Underlay (`ambient_blur`)
- **Use Case:** Panoramic Hill Country vistas, Krause Springs waterfalls, Lake Travis drone horizons, and Bluebonnet ridge silhouettes.
- **Implementation:** 
  ```bash
  [0:v]split=2[fg][bg];
  [bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5[bg];
  [fg]scale=1080:-1[fg];
  [bg][fg]overlay=0:(H-h)/2,setsar=1,fps=24,format=yuv420p[v]
  ```
- **Result:** Preserves the widescreen vista framing without cropping out horizons or mountain ridges, while bathing the vertical canvas in atmospheric, motion-matched color and depth.

---

## ✍️ Mobile Safe-Zone Kinetic Typography

Short-form platforms overlay interactive UI (usernames, sounds, like/comment buttons, caption bars) that occlude standard subtitle regions. Our kinetic subtitle engine enforces strict safe-zone guarantees:

### Safe-Zone Boundaries
- **Vertical Subtitle Anchor:** `y = 1380 – 1460` (centered horizontally at `x = 540`).
- **Clearance:** Floats 380px above the bottom edge, clearing TikTok’s sound title and description overlay, and 460px below top navigation tabs.
- **Typography:** 50px bold sans-serif with an 8px high-contrast black drop shadow/stroke for readability against bright fire, water, and sky.
- **Automatic 2-Line Wrapping:** Long bars automatically split across lines to maintain high legibility.
- **Active Word Karaoke Highlighting:** Spoken words dynamically ignite in **Amber Gold (`#F59E0B`)**, while upcoming and past words remain crisp white (`#FFFFFF`) with 0.85 opacity.

### Upper-Third Comic Ad-Lib Bursts & Modern Glassmorphic Badge
- **Title Badge Anchor (`y = 180`):** Modern frosted glassmorphic pill badge (`480x84`, radius `42px`, fill `(14, 16, 22, 215)`, subtle Texas Amber outline `(245, 158, 11, 90)`), micro-groove vinyl disc icon, clean bold header, and smooth 400ms alpha fade (`1.0s – 5.0s`).
- **Diegetic Needle Drop (`t = 2.45s`):** Stylus physical landing synchronized frame-accurately with `NeedleDrop02.mp3` transient (`adelay=2100|2100`, `rms = 7295.2`, `peak = 22576`, zero lead-in offset at `0.00s`).
- **Ad-Lib Anchor (`y = 460 – 540`):** Upper-third action band positioned strictly in negative visual space (sky, trees, open fields) avoiding subject faces and lower-third lyric subtitles.
- **Audited Acoustic Speech Alignment:** Pop-up comic bursts ignite strictly on the first spoken syllable of the ad-lib and vanish immediately on completion:
  | Act | Key | Spoken Vocal Cue | Appears | Disappears | Acoustic Anchor |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | **Act 1** | `...grotto...` | Whispered echo | `15.15s` | `15.55s` | Exits before *"I'M SO HOT THOUGH"* kicks in at 15.70s |
  | **Act 1** | `Rarw` | Hype woman growl | `16.65s` | `17.00s` | Slotted between *"THOUGH"* and *"Cold spring water"* |
  | **Act 1** | `hubba hubba` | Female ad-lib | `19.30s` | `19.85s` | Sits on ad-lib onset, clears before *"Pedernales"* |
  | **Act 1** | `ding ding` | Double chime | `20.60s` | `21.15s` | Synchronized with dings, clears before *"COLORADO"* |
  | **Act 1** | `Rio Grande!` | Shouted ad-lib | `22.35s` | `22.95s` | Locked directly over spoken ad-lib (fixed premature cutoff) |
  | **Act 1** | `Gold, baby!` | Ad-lib punchline | `27.58s` | `28.20s` | Enters on *"Gold"* and holds through *"baby!"* |
  | **Act 1** | `Right now!` | Bar 11 turnaround | `30.55s` | `30.95s` | Pops on turnaround cue without obscuring *"PRONTO"* |
  | **Act 1** | `Ride out!` | Horse reveal callout | `33.15s` | `33.55s` | Enters immediately following *"LIKE TONTO"* |
  | **Act 1** | `Talk to 'em Louie`| Brass swell callout | `46.50s` | `48.35s` | Anchored across King Louie brass swell to Bar 18 downbeat |
  | **Act 3** | `pew pew` | Guns ablaze snare | `13.80s` | `14.45s` | Strikes on dual snare hits after *"GUNS ABLAZE!"* |
  | **Act 3** | `t-t-tik tok tik` | Clock stutter vocal | `26.60s` | `27.94s` | Enters on stutter *"t-t-tik"* rather than setup *"like a"* |

---

## 📱 VoiceFi Mobile Companion PWA Integration

The VoiceFi companion web app (`http://localhost:5141` / `/pair` / `/downloads`) has been updated to seamlessly stream and distribute the native 9:16 masters:

1. **Instant Phone Pairing (`vifi rc` / `vifi companion`):**
   - Developers and mobile testers scan the local QR code to open the companion app on iOS Safari or Android Chrome.
2. **Native 9:16 Video Player:**
   - Container updated to `aspect-[9/16] max-w-[240px]` with pixel-perfect `object-cover` styling.
3. **One-Tap Save to Camera Roll:**
   - Direct download links for all 9:16 vertical cuts (`spicewood_outlaws_full_master_9_16.mp4`, `spicewood_shorts_act1_55s.mp4`, etc.) allowing immediate saving to mobile photos for direct social upload.
4. **Service Worker Invalidation:**
   - `sw.js` cache bumped to `v22` ensuring zero client cache latency on iOS devices.

---

## 🚀 Social Media Platform Publishing Playbook

### 1. YouTube Shorts (Act 1 Cutdown)
- **File:** `spicewood_shorts_act1_55s.mp4`
- **Duration:** 55.38 seconds (guaranteed under YouTube's strict 60.0s hard cap).
- **Hook Strategy:** Starts immediately with the vintage MTV chyron card, acoustic guitar intro, and hook 1.
- **Recommended Title:** `Texas Outlaw Country Meets 90s Boom Bap 🤠🔥 #Shorts #HipHop #Texas`

### 2. TikTok (Act 2 Speedburst Cutdown)
- **File:** `spicewood_reel_act2_speedburst.mp4`
- **Duration:** 1 minute 35 seconds.
- **Hook Strategy:** High-tempo muscle car revs, truck power slides, money fan, and rapid-fire Texas references.
- **Recommended Sound:** Original Audio / Master Soundtrack.

### 3. Instagram Reels & Threads (Act 3 Bonfire Finale Cutdown)
- **File:** `spicewood_reel_act3_finale.mp4`
- **Duration:** 1 minute 50 seconds.
- **Hook Strategy:** Willie Nelson's Trigger, porch whittling, exploding bonfire climax, and Krause Springs grotto.
- **Recommended Title:** `Spicewood Outlaws · The Bonfire Climax 🎸🔥 #CountryRap #TexasHillCountry`

### 4. Full Master (YouTube & Portfolio)
- **File:** `spicewood_outlaws_full_master_9_16.mp4`
- **Duration:** 4 minutes 21 seconds.
- **Format:** Long-form vertical video master.
