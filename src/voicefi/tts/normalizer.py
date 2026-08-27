"""
TTS Text & Phonetic Normalizer for VoiceFi.
Handles heteronym disambiguation (e.g. 'live' /laɪv/ vs 'live' /lɪv/),
developer acronyms, file extensions, and technical syntax for spoken speech synthesis.
"""

import re
from typing import Dict


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
    # 1. Heteronym Disambiguation: "live" (/laɪv/ vs /lɪv/)
    # =========================================================================
    # In English, "live" defaults to the verb /lɪv/ ("to live in Austin") in most TTS models.
    # When used as an adjective or adverb ("site is live", "live stream", "go live"),
    # it must be pronounced /laɪv/ ("lyve").

    # A. Preceded by linking / state verbs or adverbs ("is live", "now live", "went live", "go live", etc.)
    result = re.sub(
        r"\b(is|are|was|were|be|been|being|now|went|go|goes|going|gone|stay|stays|currently|already|also|running|deployed|up)\s+live\b",
        r"\1 lyve",
        result,
        flags=re.IGNORECASE,
    )

    # B. Preceded by tech subjects ("site is live", "server is live", "app is live")
    result = re.sub(
        r"\b(site|server|app|service|deployment|build|pipeline|dashboard|panel|stream|feed|bot|agent|endpoint|port|website)\s+(?:is|are)\s+live\b",
        r"\1 is lyve",
        result,
        flags=re.IGNORECASE,
    )

    # C. Followed by tech / media nouns ("live site", "live stream", "live session", "live dev mode", etc.)
    result = re.sub(
        r"\blive\s+(site|sites|server|servers|session|sessions|stream|streams|streaming|dev|mode|code|coding|demo|demos|logs|feed|feeds|preview|reload|updates|update|broadcast|broadcasts|traffic|test|testing|run|runs|environment|environments|view|views|companion|status|audio|transcription|transcripts|listener|inspection|loopback|speech|connection|socket|channel|deployment|version)\b",
        r"lyve \1",
        result,
        flags=re.IGNORECASE,
    )

    # D. Idioms & compound expressions ("go-live", "in live", "on live", "up and live")
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

    return result
