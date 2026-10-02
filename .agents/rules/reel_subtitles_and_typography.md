# Rule: Standard Attributed Kinetic Subtitles (Creator & Social Reels)

> **Core Philosophy**: Never trap spoken dialogue in boxes or artificial pills when agents and humans are breaking out into the real physical world. Keep the typography kinetic, floating, and human-attributed.

---

## 🚫 Strictly Forbidden in Video Overlays
1. **No Container Boxes or Cards**:
   - Never render rectangular backgrounds, rounded cards, card borders, frosted-glass panels (`backdrop-filter: blur`), or solid dark bounding boxes around spoken text.
2. **No Badge Pills or Developer Handles**:
   - Never render rounded pill containers, glowing dot tags, or terminal syntax handles (e.g. `VIV (gemini_coder)`, `// VIV [BROKEN OUT]`, `• VIV • GOOGLE ANTIGRAVITY`).
3. **No Robot / Monospace Headers on Dialogue**:
   - Spoken dialogue in social reels must not look like an IDE terminal trace.

---

## ✅ The Mandatory Standard: "words" Speaker, Organization

### 1. Structure & Layout
* **Primary Spoken Quote First**:
  - Spoken dialogue is rendered in large, bold kinetic typography enclosed in quotation marks: `“words”`.
  - Multi-layer cinematic drop shadows ensure 100% legibility against outdoor trees, cars, shirts, or complex video backgrounds:
    ```css
    text-shadow: 0 4px 20px rgba(0,0,0,0.95), 0 2px 6px rgba(0,0,0,1), 0 0 35px rgba(0,0,0,0.85);
    ```
* **Attribution Immediately Following (Below)**:
  - Speaker attribution appears directly underneath the quote using **standard English punctuation and capitalization**:
    `[Speaker Name], [Organization or Product]`
  - Standard Examples:
    - `Viv, Google Antigravity`
    - `Stefan, Claude Code`
    - `Emily, VoiceFi`
  - Subtle brand accent color with crisp text shadow (`font-size: 24px; font-weight: 600; text-shadow: 0 3px 12px rgba(0,0,0,0.95)`).

### 2. Flank Calibration (Reaction & Multi-Speaker Reels)
* **Lead Speaker (Left Flank / Pointing Action)**:
  - Slide 1 (Pointing Beat): Position at chest level (`top: 1140px; left: 48px; width: 550px`) so the creator's index finger points directly at the dialogue and attribution.
  - Subsequent Left Turns: Return to upper chest (`top: 360px; left: 48px`).
* **Counter Speaker (Right Flank)**:
  - Position at opposite shoulder (`top: 480px; right: 48px; width: 540px; text-align: right; align-items: flex-end;`).
* **Outro Narrator (Center / Lower Third)**:
  - Position centered above camera gesture (`bottom: 240px; left: 60px; right: 60px; text-align: center;`).

---

## 🛠️ Video Encoding & Player Compatibility Rule
* **Color Space Enforcement**:
  - Always convert phone HDR (Pixel 10-bit HLG `arib-std-b67` / BT.2020) to standard Rec.709 SDR:
    `-vf "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709,..."`
    `-color_primaries bt709 -color_trc bt709 -colorspace bt709`
* **Moov Atom Placement**:
  - Always pass `-movflags +faststart` so QuickTime and web browsers buffer and play immediately without black screen stalls.
