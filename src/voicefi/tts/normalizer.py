"""
TTS Text & Phonetic Normalizer for VoiceFi.
Handles heteronym disambiguation (e.g. 'live' /laɪv/ vs 'live' /lɪv/),
developer acronyms, file extensions, and technical syntax for spoken speech synthesis.
"""

import re
from enum import Enum
from typing import Dict, Optional


# Technical & developer acronyms to phonetic spoken form
TECH_SPOKEN_MAP: Dict[str, str] = {
    r"\bkubectl\b": "koob control",
    r"\bkube\s*ctl\b": "koob control",
    r"\bnpm\b": "N P M",
    r"\bpnpm\b": "P N P M",
    r"\byarn\b": "yarn",
    r"\bUUID\b": "U U I D",
    r"\bUUIDs\b": "U U I D s",
    r"\buuid\b": "U U I D",
    r"\buuids\b": "U U I D s",
    r"\bstdout\b": "standard out",
    r"\bstderr\b": "standard error",
    r"\bstdin\b": "standard in",
    r"\basync/await\b": "a-sync a-wait",
    r"\basync\s+await\b": "a-sync a-wait",
    r"\b\.tsx\b": "dot T S X",
    r"\b\.ts\b": "dot T S",
    r"\b\.py\b": "dot pie",
    r"\b\.jsonl\b": "dot J-S-O-N lines",
    r"\b\.json\b": "dot J-S-O-N",
    r"\b\.md\b": "dot M D",
    r"\b\.yaml\b": "dot yaml",
    r"\b\.yml\b": "dot yaml",
    r"\b\.env\b": "dot env",
    r"\bPostgreSQL\b": "Postgres Q L",
    r"\bpostgres\b": "Postgres",
    r"\bOAuth\b": "O Auth",
    r"\bCI/CD\b": "C I C D",
    r"\bPR\b": "P R",
    r"\bPRs\b": "P R s",
    r"\bCLI\b": "C L I",
    r"\bVAD\b": "V A D",
    r"\bSTT\b": "S T T",
    r"\bTTS\b": "T T S",
    r"\bMCP\b": "M C P",
    r"\bFastAPI\b": "Fast A P I",
    r"\bNext\.js\b": "Next J S",
    r"\bNode\.js\b": "Node J S",
    r"\bVue\.js\b": "Vue J S",
    r"\bReact\.js\b": "React J S",
    r"\bREST\s*API\b": "REST A P I",
    r"\bGraphQL\b": "Graph Q L",
    r"\bgRPC\b": "G R P C",
    r"\bHTTP/2\b": "H T T P two",
    r"\bHTTPS\b": "H T T P S",
    r"\bHTTP\b": "H T T P",
    r"\bTTFB\b": "T T F B",
    r"\bTTFA\b": "T T F A",
    r"\bTTFT\b": "T T F T",
}


def normalize_tts_text(text: str) -> str:
    """
    Transform text for natural neural speech synthesis:
    1. Heteronym Disambiguation: Disambiguate 'live' (/laɪv/ 'lyve' vs /lɪv/ 'liv').
    2. Developer Acronyms & Jargon: Expand technical abbreviations.
    3. File Extensions & Clean Formatting.
    """
    if not text or not text.strip():
        return ""

    result = text

    # =========================================================================
    # 0. Strip inline SFX tags & audio cues (e.g. [sfx:drum_smash], [sfx:applause])
    # =========================================================================
    try:
        from voicefi.audio.sfx import strip_inline_sfx_tags

        result = strip_inline_sfx_tags(result)
    except Exception:
        result = re.sub(r"[\[\(\{]\s*sfx:?\s*[\w-]+\s*[\]\)\}]", "", result, flags=re.IGNORECASE)

    # =========================================================================
    # 1. Heteronym Disambiguation: "live" (/laɪv/ vs /lɪv/)
    # =========================================================================
    # In English, "live" defaults to the verb /lɪv/ ("to live in Austin") in most TTS models.
    # When used as an adjective or adverb ("site is live", "live stream", "go live"),
    # it must be pronounced /laɪv/ ("lyve").

    # A. Preceded by determiners, articles, or possessives ("the live", "a live", "our live", "this live")
    result = re.sub(
        r"\b(the|a|an|this|that|these|those|our|your|my|their|its)\s+live\b",
        r"\1 lyve",
        result,
        flags=re.IGNORECASE,
    )

    # B. Preceded by verification, inspection, or state verbs ("verified live", "check live", "test live")
    result = re.sub(
        r"\b(verified|verify|verifying|check|checking|checked|test|testing|tested|ensure|ensuring|confirmed|confirming)\s+live\b",
        r"\1 lyve",
        result,
        flags=re.IGNORECASE,
    )

    # C. Contractions with linking verbs ("it's live", "that's live", "there's live")
    result = re.sub(
        r"\b(it's|its|that's|who's|what's|there's|here's)\s+live\b",
        r"\1 lyve",
        result,
        flags=re.IGNORECASE,
    )

    # D. Preceded by linking / state verbs or adverbs ("is live", "now live", "went live", "go live", etc.)
    result = re.sub(
        r"\b(is|are|was|were|be|been|being|now|went|go|goes|going|gone|stay|stays|currently|already|also|running|deployed|up)\s+live\b",
        r"\1 lyve",
        result,
        flags=re.IGNORECASE,
    )

    # E. Preceded by tech subjects ("site is live", "server is live", "app is live")
    result = re.sub(
        r"\b(site|server|app|service|deployment|build|pipeline|dashboard|panel|stream|feed|bot|agent|endpoint|port|website)\s+(?:is|are)\s+live\b",
        r"\1 is lyve",
        result,
        flags=re.IGNORECASE,
    )

    # F. Followed by tech / media / interaction nouns ("live site", "live pronunciation", "live mic", "live turns", etc.)
    live_nouns = (
        r"site|sites|server|servers|session|sessions|stream|streams|streaming|"
        r"dev|mode|code|coding|demo|demos|logs|log|feed|feeds|preview|previews|"
        r"reload|updates|update|broadcast|broadcasts|traffic|test|tests|testing|"
        r"run|runs|environment|environments|view|views|companion|companions|"
        r"status|audio|transcription|transcriptions|transcript|transcripts|dictation|"
        r"typing|listener|inspection|loopback|speech|connection|connections|"
        r"socket|sockets|channel|channels|deployment|deployments|version|versions|"
        r"activity|activities|turn|turns|event|events|action|actions|step|steps|"
        r"mic|mics|microphone|microphones|voice|voices|call|calls|chat|chats|"
        r"prompt|prompts|model|models|agent|agents|hud|huds|console|consoles|"
        r"data|metric|metrics|telemetry|benchmark|benchmarks|recording|recordings|"
        r"capture|captures|sample|samples|signal|signals|waveform|waveforms|"
        r"spectrum|input|inputs|output|outputs|relay|relays|sync|syncing|"
        r"state|states|loop|loops|detection|detector|monitor|monitoring|"
        r"feedback|playback|pipeline|pipelines|soundbite|soundbites|"
        r"response|responses|execution|executions|interaction|interactions|"
        r"conversation|conversations|display|displays|indicator|indicators|"
        r"pill|pills|dot|dots|badge|badges|energy|threshold|thresholds|"
        r"latency|performance|talk|talking|show|shows|wire|wires|"
        r"pronunciation|pronunciations"
    )
    result = re.sub(
        rf"\blive\s+({live_nouns})\b",
        r"lyve \1",
        result,
        flags=re.IGNORECASE,
    )

    # G. Idioms & compound expressions ("go-live", "in live", "on live", "up and live")
    result = re.sub(r"\bgo-live\b", "go-lyve", result, flags=re.IGNORECASE)
    result = re.sub(r"\b(in|on|up\s+and)\s+live\b", r"\1 lyve", result, flags=re.IGNORECASE)

    # =========================================================================
    # 2. Heteronym Disambiguation: "read" (past / adjective / tech vs present)
    # =========================================================================
    # "read-only" -> "reed-only"
    result = re.sub(r"\bread-only\b", "reed-only", result, flags=re.IGNORECASE)
    # "have read", "has read", "already read" -> "have red", "has red", "already red"
    result = re.sub(r"\b(have|has|had|already)\s+read\b", r"\1 red", result, flags=re.IGNORECASE)

    # =========================================================================
    # 3. Developer Acronyms & Spoken Code
    # =========================================================================
    for pattern, replacement in TECH_SPOKEN_MAP.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # =========================================================================
    # 4. Ellipses & Dramatic Pauses (prevents orphan punctuation in TTS pipeline)
    # =========================================================================
    # If preceded by sentence-ending punctuation (!, ?), turn ellipsis into clean space
    result = re.sub(r"([!?])\s*(\.{2,}|…)\s*", r"\1 ", result)
    # Otherwise replace standalone ellipsis with a natural comma pause
    result = re.sub(r"\s*(\.{2,}|…)\s*", ", ", result)
    # Clean double commas or leading commas
    result = re.sub(r",\s*,+", ", ", result)
    result = re.sub(r"^\s*,\s*", "", result)

    return result.strip()


def normalize_stt_text(raw_text: str) -> str:
    """
    Normalize raw Whisper STT transcription into canonical developer syntax
    using the recursive phonetic self-learning engine.
    """
    from voicefi.learning.phonetic import PhoneticLearner

    return PhoneticLearner.get_instance().normalize_stt(raw_text)


class AppStyleContext(str, Enum):
    CHAT = "chat"  # Slack, Discord, Microsoft Teams, Messages, Telegram, WhatsApp
    EMAIL = "email"  # Apple Mail, Outlook, Gmail, Superhuman
    CODE = "code"  # Cursor, VS Code, Antigravity, Windsurf, Xcode, Terminal, iTerm2, Warp, Ghostty
    DOCS = "docs"  # Notion, Obsidian, Apple Notes, Google Docs, Confluence, Craft
    GENERAL = "general"  # Safari, Chrome, default desktop apps


def classify_app_context(app_name: str) -> AppStyleContext:
    """Classify frontmost macOS application into semantic communication context."""
    if not app_name:
        return AppStyleContext.GENERAL
    low = app_name.lower().strip()
    if any(
        k in low
        for k in ("slack", "discord", "teams", "messages", "telegram", "whatsapp", "signal")
    ):
        return AppStyleContext.CHAT
    if any(
        k in low
        for k in ("mail", "outlook", "gmail", "superhuman", "thunderbird", "spark", "airmail")
    ):
        return AppStyleContext.EMAIL
    if any(
        k in low
        for k in (
            "cursor",
            "code",
            "visual studio",
            "antigravity",
            "windsurf",
            "xcode",
            "terminal",
            "iterm",
            "warp",
            "ghostty",
            "alacritty",
            "kitty",
            "wezterm",
            "intellij",
            "pycharm",
            "webstorm",
        )
    ):
        return AppStyleContext.CODE
    if any(
        k in low
        for k in ("notion", "obsidian", "notes", "docs", "confluence", "craft", "bear", "pages")
    ):
        return AppStyleContext.DOCS
    return AppStyleContext.GENERAL


def strip_verbal_fillers(text: str) -> str:
    """
    Remove verbal disfluencies and filler words ('um', 'uh', 'ah', 'like', 'you know', 'basically', stutter duplicates)
    while preserving code keywords, CLI flags, and technical terms.
    """
    if not text or not text.strip():
        return ""

    result = text.strip()

    # 1. Standalone fillers at start of sentence or mid-sentence
    result = re.sub(r"(?i)(?:,\s*)?\b(?:um|uh|er|ah|eh|erm)\b[,.\s]*", " ", result)

    # 2. Filler phrases with commas or surrounding pauses
    result = re.sub(
        r"(?i)\b(?:you know|i mean|(?:so\s+)?basically|like I said|to be honest)\b[,]*\s*",
        " ",
        result,
    )

    # 3. Filler 'like' conversational ticks
    result = re.sub(
        r"(?i)\b(\w+)\s+like\s+(really|super|just|kinda|sorta|to|for|about|in|on|with|going|trying)\b",
        r"\1 \2",
        result,
    )
    result = re.sub(
        r"(?i)\b(is|was|are|were|be|been|have|had|would|could|should)\s+like\s+", r"\1 ", result
    )

    # 4. Repeated stutter duplicates ('the the', 'in in', 'that that', 'to to', 'we we', 'is is', 'and and')
    # Protect CLI flag words like 'dash dash', 'minus minus', 'plus plus'
    result = re.sub(r"(?i)\b(?!(?:dash|minus|dot|plus)\b)(\w{1,8})\s+\1\b", r"\1", result)

    # 5. Clean up resulting punctuation artifacts & whitespace
    result = re.sub(r"\s+([,.:;?!])", r"\1", result)
    result = re.sub(r",\s*,+", ", ", result)
    result = re.sub(r"^\s*[,.]\s*", "", result)
    result = re.sub(r"\s+", " ", result).strip()

    if result and result[0].islower():
        result = result[0].upper() + result[1:]

    return result


def format_for_app_context(
    text: str, app_name: Optional[str] = None, context: Optional[AppStyleContext] = None
) -> str:
    """
    Format and adapt speech transcription based on the frontmost application context:
    - Chat (Slack/Discord): conversational, concise, bullet points if listing items.
    - Email (Mail/Outlook): proper capitalization, greeting separation, polite punctuation.
    - Code IDE/Terminal (Cursor/VS Code/Terminal): technical formatting, code symbols, inline flags.
    - Docs (Notion/Obsidian): structured markdown paragraphs & lists.
    - General: clean standard capitalization & punctuation.
    """
    if not text or not text.strip():
        return ""

    cleaned = strip_verbal_fillers(text)
    ctx = context or classify_app_context(app_name or "")

    if ctx == AppStyleContext.CODE:
        # Code formatting: preserve technical operators and flags
        cleaned = re.sub(r"(?i)\bdouble equals\b", "==", cleaned)
        cleaned = re.sub(r"(?i)\btriple equals\b", "===", cleaned)
        cleaned = re.sub(r"(?i)\bnot equal to\b", "!=", cleaned)
        cleaned = re.sub(r"(?i)\barrow function\b", "=>", cleaned)
        cleaned = re.sub(r"(?i)\bdot length\b", ".length", cleaned)
        cleaned = re.sub(r"(?i)\bdot json\b", ".json", cleaned)
        cleaned = re.sub(r"(?i)\bminus minus\s*([a-zA-Z0-9_-]+)", r"--\1", cleaned)
        cleaned = re.sub(r"(?i)\bdash dash\s*([a-zA-Z0-9_-]+)", r"--\1", cleaned)
        return cleaned

    elif ctx == AppStyleContext.CHAT:
        # Chat formatting: concise, multi-bullet points if listing items ("first... second...")
        if re.search(
            r"(?i)\b(first|1st|one)\b.*?\b(second|third|2nd|3rd|two|three|next|then|finally|also)\b",
            cleaned,
        ):
            parts = re.split(
                r"(?i)(?:\bfirst\b|\bsecond\b|\bthird\b|\bnext\b|\bthen\b|\bfinally\b|\balso\b)",
                cleaned,
            )
            lines = [p.strip().strip(",.- ") for p in parts if p.strip()]
            if len(lines) >= 2:
                return "\n".join([f"• {l.capitalize()}" for l in lines])
        return cleaned

    elif ctx == AppStyleContext.EMAIL:
        # Email formatting: ensure trailing period and clear sentence spacing
        if cleaned and not cleaned.endswith((".", "!", "?")):
            cleaned += "."
        return cleaned

    elif ctx == AppStyleContext.DOCS:
        # Docs / Notes formatting: markdown friendly
        if "\n" not in cleaned and len(cleaned.split()) > 30:
            sentences = re.split(r"(?<=[.!?])\s+", cleaned)
            if len(sentences) >= 3:
                return " ".join(sentences[:2]) + "\n\n" + " ".join(sentences[2:])
        return cleaned

    return cleaned


_REPETITION_RUN_THRESHOLD = 6
_MAX_REPETITION_UNIT_CHARS = 60


def _token_key(word: str) -> str:
    """Normalize a token for repetition comparison — strip surrounding punctuation and lowercase."""
    return re.sub(r"[^\w]", "", word).lower()


def collapse_repetitive_artifacts(text: str, min_run: int = _REPETITION_RUN_THRESHOLD) -> str:
    """
    Deterministically strip Whisper STT hallucination loops in <0.5ms.

    Handles two primary failure modes:
    1. Word-level: any single token repeated consecutively min_run+ times
       (e.g., 'URL URL URL URL URL URL' -> stripped).
    2. Character-level: any phrase (2-60 chars) repeated consecutively min_run+ times
       (e.g., 'Thank you for watching. Thank you for watching...' or CJK loops -> stripped).

    Safe for human rhetorical repetition ('no, no, no' = 3; 'yeah yeah yeah' = 3)
    because they remain below the min_run threshold.
    """
    if not text or not text.strip():
        return text

    # 1. Word-level pass
    words = text.split()
    if len(words) >= min_run:
        out = []
        i = 0
        while i < len(words):
            key = _token_key(words[i])
            j = i
            if key:
                while j < len(words) and _token_key(words[j]) == key:
                    j += 1
            else:
                j = i + 1
            if (j - i) < min_run:
                out.extend(words[i:j])
            i = j
        text = " ".join(out)

    # 2. Character-level regex pass (multi-word phrases and unsegmented/CJK text)
    pattern = re.compile(
        r"(.{2," + str(_MAX_REPETITION_UNIT_CHARS) + r"}?)\1{" + str(min_run - 1) + r",}",
        flags=re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        unit = m.group(1).strip()
        result = pattern.sub("", text)
        # If the leftover text is just a boundary echo of the repeating unit, drop it
        if result.strip() and result.strip() == unit:
            result = ""
        elif result.endswith(unit):
            result = result[:-len(unit)].rstrip()
        elif result.startswith(unit):
            result = result[len(unit):].lstrip()
        text = re.sub(r"\s+", " ", result).strip()

    # 3. Sentence & multi-word clause duplicate pass (collapses 2-run repetitions of sentences or >=4 word phrases)
    return _collapse_sentence_and_clause_duplicates(text)


def _collapse_sentence_and_clause_duplicates(text: str) -> str:
    """
    Collapse 2-run duplicate sentences or long phrases (>= 3 words / >= 12 chars).
    Preserves rhetorical repetition ('No, no, no', 'Yeah yeah yeah').
    """
    if not text or len(text.strip()) < 15:
        return text

    # Pass A: Punctuation-delimited sentences
    parts = re.split(r'([.!?;\n]+(?:\s+|$))', text)
    if len(parts) > 2:
        reconstructed = []
        last_norm = ""
        for i in range(0, len(parts), 2):
            clause = parts[i]
            sep = parts[i + 1] if i + 1 < len(parts) else ""
            if not clause.strip():
                reconstructed.append(clause + sep)
                continue
            norm = re.sub(r"[^\w\s]", "", clause).strip().lower()
            norm_words = norm.split()
            # Only collapse if clause is substantial (>= 3 words and >= 10 chars)
            if len(norm_words) >= 3 and len(norm) >= 10 and norm == last_norm:
                continue
            last_norm = norm
            reconstructed.append(clause + sep)
        text = "".join(reconstructed).strip()

    # Pass B: Unpunctuated phrase duplication (common in STT)
    # Check if a multi-word sequence (k >= 4 words) repeats consecutively: S S -> S
    tokens = text.split()
    n = len(tokens)
    if n >= 8:
        max_k = min(n // 2, 40)
        for k in range(max_k, 3, -1):
            i = 0
            while i + 2 * k <= len(tokens):
                chunk1 = " ".join(_token_key(w) for w in tokens[i : i + k])
                chunk2 = " ".join(_token_key(w) for w in tokens[i + k : i + 2 * k])
                if chunk1 and chunk1 == chunk2:
                    tokens = tokens[: i + k] + tokens[i + 2 * k :]
                else:
                    i += 1
        text = " ".join(tokens)

    return text.strip()


def inject_documentary_breathing_pauses(text: str) -> str:
    """
    Format text for nature documentary style narration by inserting deliberate
    breathing pauses and dramatic ellipses before revelation clauses.
    """
    if not text or not text.strip():
        return text

    t = text.strip()

    # Expand intro phrases into breath pauses (only at sentence or clause boundaries)
    intro_patterns = [
        (r"(^|[.!?;]\s*)(And here)[,.]?\s*", r"\1And here... "),
        (r"(^|[.!?;]\s*)(Look closely)[,.]?\s*", r"\1Look closely... "),
        (r"(^|[.!?;]\s*)(Remarkable)[,.]?\s*", r"\1Remarkable... "),
        (r"(^|[.!?;]\s*)(Extraordinary)[,.]?\s*", r"\1Extraordinary... "),
        (r"(^|[.!?;]\s*)(Quite astonishing)[,.]?\s*", r"\1Quite astonishing... "),
        (r"(^|[.!?;]\s*)(Here in the)[,.]?\s*", r"\1Here... in the "),
        (r"(^|[.!?;]\s*)(Notice how)[,.]?\s*", r"\1Notice... how "),
        (r"(^|[.!?;]\s*)(Yet)[,.]?\s+", r"\1Yet... "),
    ]
    for pat, rep in intro_patterns:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)

    # Insert dramatic pauses at major clause boundaries if not already punctuated with ellipsis
    t = re.sub(r",\s*(we discover|we find|lies|awaits|emerges|survives)\b", r"... \1", t, flags=re.IGNORECASE)

    # Normalize multiple ellipses or spaces (e.g. '... ...' or '... .' -> '...')
    t = re.sub(r"(?:\s*\.+){2,}\s*", "... ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
