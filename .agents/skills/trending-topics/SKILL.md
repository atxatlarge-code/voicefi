---
name: trending-topics
description: Discovers high-engagement, viral, and trending topics across X/Twitter, Reddit, Hacker News, and the tech web. Filters for outsized relative engagement, practitioner gold, and friction points, then transmutates them into ready-to-record vertical video reels, X threads, and LinkedIn posts. Inspired by Edward Sturm's Grok viral content automation.
---

# 📡 Trending Topics & Viral Content Radar — VoiceFi™

Specialized skill for discovering breakout, high-velocity topics across social media and developer communities, identifying outsized relative engagement (especially from smaller practitioners), and automatically transmutating trends into high-converting video reels, X threads, and thought leadership posts.

---

## 🎯 Core Philosophy & The "Verbatim Video" Law

Modeled after Edward Sturm’s viral Grok automation framework (*"This Grok Automation Got Me 2,400,000 Views in Two Weeks"*):

> **The Core Law:** *If something in your niche is going viral on X or developer communities, and you simply read the core post or react to it with a sharp practitioner hook on video, it will go viral again on vertical video (TikTok, Instagram Reels, YouTube Shorts).*

### The 4 Pillars of High-Signal Content Discovery:
1. **Relative Outperformance Over Raw Follower Count**:
   - A post with 100,000 views from an account with 3,000 followers is **pure validated gold**—the topic succeeded on pure intrinsic merit.
   - For mega-accounts (>100k followers), views must be evaluated relative to their recent average.
2. **Short, Punchy & Verbatim-Ready**:
   - Strongly prefer posts under **280–400 characters** or concise quotes with concrete numbers, terminal setups, or contrarian takeaways.
   - Long, rambling threads get deprioritized.
3. **The Diversified Net (12–20 Parallel Search Vectors)**:
   - Never query just one head term. Mix **Head Topics**, **Ultra-Tactical Workflows**, **Pain Points / Rants**, **Algorithm / Tooling Shifts**, and **Wins & Recoveries**.
4. **Instant Transmutation**:
   - Every detected trend is immediately formatted into three ready-to-ship assets:
     - **Vertical Video Reel Hook** (calibrated for [`reel-scriptwriter`](file:///Users/jaketrigg/Projects/vifi.co/.agents/skills/reel-scriptwriter/SKILL.md)).
     - **X / Twitter Post or Thread Opener**.
     - **LinkedIn / Founder Insight**.

---

## 🛠️ Step-by-Step Discovery Protocol

When the user asks for trending topics, viral post ideas, or content inspiration:

```
[User Request / Scheduled Cron]
               │
               ▼
[Step 1: Define Target Niche & Vectors]
   ├─ Default: Voice AI, AI Coding Agents (Antigravity, Claude Code, Cursor), MCP, Developer Workflow
   └─ Custom: Any niche specified by user (SEO, FinTech, Indie Hacking, LLMO, etc.)
               │
               ▼
[Step 2: Run Live Radar Sweep]
   ├─ Execute: `python3 scripts/trending_radar.py --niche "<niche>"`
   └─ Execute: `search_web` parallel queries across X (`site:x.com`), Reddit, and news
               │
               ▼
[Step 3: Filter & Score Relative Engagement]
   ├─ Discard generic promotional spam, giveaways, or low-effort AI slop
   └─ Score outperformance ratio (views / followers or comments / score)
               │
               ▼
[Step 4: Transmutate into Production Formats]
   ├─ 1. Vertical Video Reel Hook (12-16 words per card, persona assignment)
   ├─ 2. X / Twitter Post / Thread Opener
   ├─ 3. LinkedIn Post Draft
   └─ 4. Meta Patterns & Emerging Signals
```

---

## 🔍 The Parallel Search Net (Query Templates)

When executing web searches or X sweeps, construct queries across these 4 tactical categories:

### 1. High-Impact Head Queries (Broad Virality)
- `site:x.com ("Voice AI" OR "AI agents" OR "Claude Code" OR "Antigravity") (min_faves:50 OR "views")`
- `site:x.com ("MCP" OR "Model Context Protocol") (min_faves:25)`

### 2. Practitioner Wins, Setups & Benchmarks (Small-Account Outperformance)
- `site:x.com ("how I setup" OR "how I automated" OR "before and after" OR "shipped" OR "my workflow") (Claude OR Cursor OR Antigravity OR "voice")`
- `site:reddit.com/r/LocalLLaMA ("benchmark" OR "speed" OR "latency" OR "quant")`

### 3. Controversy, Rants & Friction Points (High Discussion Velocity)
- `site:x.com ("stopped using" OR "why I hate" OR "unpopular opinion" OR "broke my" OR "terrible") ("AI" OR "terminal" OR "agent")`
- `site:reddit.com/r/programming ("controversial" OR "rant" OR "deprecated")`

### 4. Secret Shortcuts & Undocumented Features (15s Video Bait)
- `site:x.com ("undocumented" OR "hidden trick" OR "secret shortcut" OR "pro tip" OR "did you know") ("macOS" OR "Cursor" OR "terminal" OR "VS Code")`

---

## 📋 Standardized Output Dossier Schema

Present results in this structured format:

````markdown
# 📡 Viral Content Radar: [Niche] — [Date]

## 🚀 Top Breakout Topics & Validated Ideas

### 1. [Catchy Trend Title / Angle]
- **Source & Platform**: [Link to Tweet / Reddit / HN post]
- **Author**: `@handle` (Followers: `~X,XXX` — *Outperformance: 12x typical account reach*)
- **Engagement**: `X,XXX likes` · `Y,YYY reposts` · `Z,ZZZ views` · `C comments`
- **The Core Insight**: One direct sentence summarizing the breakthrough or controversy.
- **The Verbatim / Reaction Hook**:
  > *"Direct quote of the punchiest 1–2 sentences from the source."*
- **Why It Works**: The psychological trigger (contrarian take, secret shortcut, developer pain, paradigm shift).

#### 🎬 Format A: Vertical Video Reel Hook (TikTok / Reels / Shorts)
- **Persona / Character**: Viv (Energetic Momentum) / Steffan (Dry Critic) / Jake (Builder)
- **Slide 1 (3-Second Hook)**: `[10–14 words max — large kinetic text]`
- **Slide 2 (The Shocking Stat / Reality)**: `[10–14 words max]`
- **Slide 3 (The Punchline / VoiceFi Twist)**: `[10–14 words max + [sfx:drum_smash]]`
- **Visual Cue**: Split-screen showing glowing terminal void vs hands-free voice pacing.

#### 𝕏 Format B: X / Twitter Post / Thread Opener
```text
[Punchy contrarian 1-2 sentence hook]

[2-3 bullet point breakdown of what actually happened]

[Takeaway question to drive replies]
```

#### 💼 Format C: LinkedIn / Founder Insight
```text
[Hook addressing engineering leaders or developers]

[Contextual architecture explanation or productivity lesson]

[Call to action: What are you seeing in your stack?]
```

---

## 🧠 Meta Patterns & Emerging Signals (2–4 Bullets)
- **Signal 1**: [Recurring theme observed across multiple platforms]
- **Signal 2**: [New tool or protocol gaining sudden traction]
- **Signal 3**: [Shift in developer sentiment from skepticism to adoption]
````

---

## 🔄 Direct Production Pipeline Integration

Once an idea is selected, pipe it immediately into the next stage of content production:

### 1. Turn Idea into a Multi-Agent Script:
Invoke [`reel-scriptwriter`](file:///Users/jaketrigg/Projects/vifi.co/.agents/skills/reel-scriptwriter/SKILL.md) to generate dialogue banter:
```bash
python3 scripts/generate_conversational_script.py \
  --topic "Latency vs Sub-150ms Barge-In" \
  --style banter \
  --output marketing/social/reels/006_trending_topic.json
```

### 2. Render Full Video Reel with VoiceFi:
Invoke [`social-reel-producer`](file:///Users/jaketrigg/Projects/vifi.co/.agents/skills/social-reel-producer/SKILL.md) to synthesize neural audio and render hardware-accelerated 9:16 video:
```bash
python3 marketing/social/generate_hybrid_master_reel.py
```

---

## ⏰ Daily Automation Setup via `/schedule`

To receive a daily viral briefing automatically every morning:

```python
schedule(
    CronExpression="0 8 * * 1-5",  # Weekdays at 8:00 AM CT
    Prompt="Run trending-topics radar for Voice AI, AI coding agents, and developer pain points. Output the top 3 validated video hooks and X drafts.",
    IsDaemon=true
)
```
Or recommend the user type:
```
/schedule "Run trending-topics radar daily at 8am CT"
```
