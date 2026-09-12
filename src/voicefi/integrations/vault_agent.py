"""
Vault Agent Integration for VoiceFi.
Provides conversational Q&A, active note summaries, and auditory briefings for Obsidian vaults.

Question answering runs in two stages:

1. **Retrieval** — a ripgrep sweep across every markdown note in the vault
   (:meth:`VaultAgent.search_vault`). This needs no API key and no network.
2. **Synthesis** — an optional LLM pass over the retrieved snippets. When no
   provider is configured (``get_active_provider() == "heuristic"``), the agent
   speaks the strongest snippet with its source note instead. Adding a Gemini
   key or starting Ollama upgrades the answers with no code change.
"""

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from voicefi.config import VoiceFiConfig, load_config
from voicefi.redaction import redact_secrets

logger = logging.getLogger(__name__)

# Directories that are never user knowledge.
_EXCLUDED_GLOBS = (
    "!.obsidian/**",
    "!.trash/**",
    "!.git/**",
    "!node_modules/**",
)

# Dropped from spoken queries before retrieval — they match everything.
_STOPWORDS: Set[str] = {
    # Short function words — these match nearly every note.
    "all", "and", "any", "are", "but", "can", "day", "did", "not", "for",
    "get", "got", "had", "has", "her", "him", "his", "how", "its", "let",
    "may", "new", "now", "off", "one", "our", "out", "own", "per", "put",
    "say", "see", "the", "too", "two", "use", "via", "was", "way", "who",
    "why", "yet", "you",
    "about", "after", "again", "against", "another", "anything", "around",
    "because", "been", "before", "being", "between", "both", "could", "did",
    "does", "doing", "down", "during", "each", "even", "ever", "every",
    "from", "further", "have", "having", "here", "hers", "herself", "himself",
    "into", "itself", "just", "like", "look", "made", "make", "many", "more",
    "most", "much", "must", "myself", "need", "only", "other", "over", "own",
    "recall", "remember", "said", "same", "should", "show", "some", "such",
    "tell", "than", "that", "their", "them", "then", "there", "these", "they",
    "thing", "things", "this", "those", "through", "under", "until", "very",
    "want", "were", "what", "when", "where", "which", "while", "will", "with",
    "would", "your", "yours", "yourself",
}

_SEARCH_TIMEOUT_S = 5.0
_SYNTHESIS_TIMEOUT_S = 6.0
_MAX_FILE_BYTES = 2_000_000


class VaultAgent:
    """Conversational assistant for Obsidian knowledge vaults."""

    def __init__(self, config: Optional[VoiceFiConfig] = None):
        self.config = config or load_config()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def answer_vault_query(
        self,
        query: str,
        note_title: str = "",
        note_content: str = "",
        vault_path: Optional[Path] = None,
        search_vault: bool = True,
    ) -> Dict[str, Any]:
        """
        Process a spoken query against the active note and the wider vault.
        Generates an auditory-friendly response calibrated for speech synthesis.
        """
        clean_query = query.strip()
        lower_q = clean_query.lower()

        # Phonetic normalization for common STT phonetic slips
        if any(
            w in lower_q
            for w in [
                "some racist",
                "some raise",
                "some race",
                "some race is",
                "summer eyes",
                "summerize",
                "summarise",
                "summarize",
            ]
        ):
            lower_q = "summarize this note"

        # 1. Handle direct summarization requests
        if any(
            w in lower_q
            for w in [
                "summarize",
                "summary",
                "give me a summary",
                "overview",
                "what is this note about",
            ]
        ):
            return self._summarize_note(note_title, note_content)

        # 2. Handle task / action item extraction
        if any(
            w in lower_q
            for w in ["tasks", "action items", "todos", "what do i need to do", "blockers"]
        ):
            return self._extract_action_items(note_title, note_content)

        # 3. Handle contextual question answering
        return self._answer_question(
            clean_query,
            note_title,
            note_content,
            vault_path=vault_path,
            search_vault=search_vault,
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    @staticmethod
    def extract_search_terms(query: str) -> List[str]:
        """Reduce a spoken query to the distinctive words worth searching for."""
        words = re.findall(r"\b\w{3,}\b", query.lower())
        terms: List[str] = []
        for w in words:
            if w in _STOPWORDS or w.isdigit():
                continue
            if w not in terms:
                terms.append(w)
        return terms

    def resolve_vault(self, vault_path: Optional[Path] = None) -> Optional[Path]:
        """Resolve the vault to search, honouring an explicit override."""
        if vault_path:
            vp = Path(vault_path).expanduser()
            return vp if vp.is_dir() else None
        from voicefi.integrations.obsidian import get_primary_vault

        return get_primary_vault(self.config)

    def search_vault(
        self,
        query: str,
        vault_path: Optional[Path] = None,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search every markdown note in the vault for the query terms.

        Returns a ranked list of ``{note, path, line, snippet, matched_terms, score}``.
        Ranking favours notes matching the most distinct terms, then match density.
        Never raises — retrieval failure degrades to an empty list.
        """
        terms = self.extract_search_terms(query)
        if not terms:
            return []

        vault = self.resolve_vault(vault_path)
        if not vault:
            return []

        raw = self._ripgrep(terms, vault)
        if raw is None:
            raw = self._python_scan(terms, vault)

        # Group hits by note and score.
        by_file: Dict[str, Dict[str, Any]] = {}
        for path_str, line_no, text in raw:
            entry = by_file.setdefault(
                path_str,
                {"matched_terms": set(), "lines": [], "best_line": line_no, "best_count": 0},
            )
            lowered = text.lower()
            hit_terms = {t for t in terms if t in lowered}
            entry["matched_terms"].update(hit_terms)
            entry["lines"].append((line_no, text))
            if len(hit_terms) > entry["best_count"]:
                entry["best_count"] = len(hit_terms)
                entry["best_line"] = line_no

        # Adaptive term weighting: a term appearing in most matched notes is
        # uninformative regardless of whether it is in the stopword list, so
        # weight each term by inverse document frequency and drop the dregs.
        doc_freq: Dict[str, int] = {}
        for entry in by_file.values():
            for t in entry["matched_terms"]:
                doc_freq[t] = doc_freq.get(t, 0) + 1

        n_files = len(by_file)
        if n_files >= 4:
            ubiquitous = {t for t, df in doc_freq.items() if df >= 0.5 * n_files}
            if len(ubiquitous) < len(doc_freq):  # never drop every term
                for entry in by_file.values():
                    entry["matched_terms"] -= ubiquitous

        results: List[Dict[str, Any]] = []
        for path_str, entry in by_file.items():
            if not entry["matched_terms"]:
                continue
            p = Path(path_str)
            score = sum(10.0 / doc_freq[t] for t in entry["matched_terms"])
            score += min(len(entry["lines"]), 5) * 0.2
            score = round(score, 2)
            results.append(
                {
                    "note": p.stem,
                    "path": path_str,
                    "line": entry["best_line"],
                    # Choke point: snippets feed TTS, the WebSocket/relay
                    # broadcast, the MCP result, and the LLM context. Redact here
                    # so no downstream consumer can forget to.
                    "snippet": redact_secrets(
                        self._extract_context(p, entry["best_line"])
                    ),
                    "matched_terms": sorted(entry["matched_terms"]),
                    "score": score,
                }
            )

        results.sort(key=lambda r: (r["score"], r["note"]), reverse=True)
        return results[:max_results]

    def _ripgrep(self, terms: List[str], vault: Path) -> Optional[List[tuple]]:
        """Run ripgrep across the vault. Returns None if rg is unavailable."""
        rg = shutil.which("rg")
        if not rg:
            return None

        cmd = [
            rg,
            "--no-heading",
            "--with-filename",
            "--line-number",
            "--ignore-case",
            "--no-messages",
            "--max-columns",
            "400",
            "--glob",
            "*.md",
        ]
        for g in _EXCLUDED_GLOBS:
            cmd.extend(["--glob", g])
        for t in terms:
            cmd.extend(["-e", re.escape(t)])
        cmd.append(str(vault))

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_SEARCH_TIMEOUT_S
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("vault ripgrep failed (%s); falling back to python scan", e)
            return None

        # rg exits 1 on "no matches", which is not an error for us.
        if proc.returncode not in (0, 1):
            logger.warning("vault ripgrep exit %s; falling back", proc.returncode)
            return None

        hits: List[tuple] = []
        for line in proc.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            path_str, line_no_str, text = parts
            try:
                hits.append((path_str, int(line_no_str), text))
            except ValueError:
                continue
        return hits

    def _python_scan(self, terms: List[str], vault: Path) -> List[tuple]:
        """Pure-python fallback scan when ripgrep is unavailable."""
        hits: List[tuple] = []
        skip = {".obsidian", ".trash", ".git", "node_modules"}
        for md in vault.rglob("*.md"):
            if any(part in skip for part in md.parts):
                continue
            try:
                if md.stat().st_size > _MAX_FILE_BYTES:
                    continue
                text = md.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                lowered = line.lower()
                if any(t in lowered for t in terms):
                    hits.append((str(md), i, line[:400]))
        return hits

    @staticmethod
    def _extract_context(path: Path, line_no: int, window: int = 2) -> str:
        """Pull the lines surrounding a match so the snippet reads as prose."""
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return ""
        start = max(0, line_no - 1 - window)
        end = min(len(lines), line_no + window)
        chunk = " ".join(x.strip() for x in lines[start:end] if x.strip())
        return re.sub(r"\s+", " ", chunk).strip()

    # ------------------------------------------------------------------
    # Note-scoped handlers (unchanged behaviour)
    # ------------------------------------------------------------------

    def _summarize_note(self, title: str, content: str) -> Dict[str, Any]:
        """Create a punchy spoken summary of the note."""
        if not content.strip():
            spoken = f"Your note {title or 'document'} is currently empty."
            return {"spoken_response": spoken, "text_summary": spoken, "action": "summarize"}

        # Extract headings and bullet points
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        headings = [re.sub(r"^#+\s*", "", l) for l in lines if l.startswith("#")]
        bullets = [
            re.sub(r"^[-*]\s*(\[[ xX]\]\s*)?", "", l)
            for l in lines
            if l.startswith("-") or l.startswith("*")
        ]

        total_words = len(content.split())
        title_str = title if title else "active note"

        if headings and bullets:
            top_heading = headings[0]
            bullet_sample = ", ".join(bullets[:3])
            spoken = f"Here is a summary of {title_str}. It focuses on {top_heading}, with key items including {bullet_sample}."
        elif headings:
            sections_str = ", ".join(headings[:3])
            spoken = (
                f"{title_str} contains {total_words} words across sections covering {sections_str}."
            )
        elif bullets:
            spoken = f"{title_str} has {len(bullets)} items. The top points are: {', '.join(bullets[:3])}."
        else:
            first_few = " ".join(lines[:2])
            # Strip markdown formatting
            first_few = re.sub(r"[*_#`\[\]]", "", first_few)
            spoken = f"{title_str} is about {first_few[:180]}."

        return {
            "spoken_response": spoken,
            "text_summary": spoken,
            "action": "summarize",
            "title": title,
            "word_count": total_words,
        }

    def _extract_action_items(self, title: str, content: str) -> Dict[str, Any]:
        """Extract open checkboxes and tasks from the note."""
        open_tasks = re.findall(r"^[-*]\s*\[ \]\s*(.+)$", content, re.MULTILINE)
        completed_tasks = re.findall(r"^[-*]\s*\[[xX]\]\s*(.+)$", content, re.MULTILINE)

        if open_tasks:
            count = len(open_tasks)
            task_str = ", ".join(open_tasks[:3])
            more_str = f", plus {count - 3} more" if count > 3 else ""
            spoken = f"You have {count} open task{'s' if count > 1 else ''} in {title or 'this note'}: {task_str}{more_str}."
        elif completed_tasks:
            spoken = f"All {len(completed_tasks)} tasks in {title or 'this note'} are marked complete! Nice work."
        else:
            spoken = f"I didn't find any checkbox tasks in {title or 'this note'}."

        return {
            "spoken_response": spoken,
            "open_tasks": open_tasks,
            "completed_tasks": completed_tasks,
            "action": "tasks",
        }

    # ------------------------------------------------------------------
    # Question answering
    # ------------------------------------------------------------------

    def _answer_question(
        self,
        query: str,
        title: str,
        content: str,
        vault_path: Optional[Path] = None,
        search_vault: bool = True,
    ) -> Dict[str, Any]:
        """Answer a question using vault-wide retrieval, then optional synthesis."""
        hits = self.search_vault(query, vault_path=vault_path) if search_vault else []

        # Fall back to the active note when the vault yields nothing.
        if not hits and content.strip():
            snippet = redact_secrets(self._best_paragraph(query, content))
            if snippet:
                hits = [
                    {
                        "note": title or "active note",
                        "path": "",
                        "line": 0,
                        "snippet": snippet,
                        "matched_terms": [],
                        "score": 1,
                    }
                ]

        if not hits:
            title_str = title or "your vault"
            return {
                "spoken_response": f"I searched {title_str} but found nothing matching '{query}'.",
                "action": "answer",
                "query": query,
                "sources": [],
                "provider": "none",
                "matched_snippet": "",
            }

        spoken = self._synthesize_answer(query, hits)
        provider = "llm"
        if not spoken:
            spoken = self._speak_snippet(hits[0])
            provider = "retrieval"

        return {
            "spoken_response": spoken,
            "action": "answer",
            "query": query,
            "sources": [
                {"note": h["note"], "path": h["path"], "line": h["line"]} for h in hits
            ],
            "provider": provider,
            # Back-compat with callers that read the old single-snippet key.
            "matched_snippet": hits[0]["snippet"],
        }

    @staticmethod
    def _best_paragraph(query: str, content: str) -> str:
        """Keyword-overlap pick from a single note (legacy in-note fallback)."""
        query_words = set(re.findall(r"\b\w{4,}\b", query.lower()))
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        best_p, best_score = "", 0
        for p in paragraphs:
            p_words = set(re.findall(r"\b\w{4,}\b", p.lower()))
            overlap = len(query_words.intersection(p_words))
            if overlap > best_score:
                best_score, best_p = overlap, p
        return best_p if best_score > 0 else ""

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Strip markdown syntax that reads badly through a TTS engine."""
        text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links / images
        text = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", text)  # wikilinks
        text = re.sub(r"[*_#`>]", "", text)
        text = re.sub(r"^\s*[-+]\s*(\[[ xX]\]\s*)?", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def _speak_snippet(self, hit: Dict[str, Any]) -> str:
        """Retrieval-only answer: read the strongest snippet with its source."""
        # Redact before cleaning — see _synthesize_answer for why order matters.
        snippet = self._clean_for_speech(redact_secrets(hit.get("snippet", "")))[:240]
        note = hit.get("note") or "your vault"
        if not snippet:
            return f"I found a match in {note}, but couldn't read the surrounding text."
        return f"From your note {note}: {snippet}"

    def _synthesize_answer(self, query: str, hits: List[Dict[str, Any]]) -> Optional[str]:
        """
        Ask the configured LLM to turn retrieved snippets into a spoken answer.
        Returns None when no provider is available or the call fails, which is
        the normal path on a machine with no API key.
        """
        try:
            from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine

            engine = GeminiIntelligenceEngine(self.config)
            if not engine.is_available():
                return None

            # Redact BEFORE cleaning: _clean_for_speech strips underscores and
            # markdown, which mangles a secret past its own pattern (re_xxx ->
            # rexxx) while leaving it perfectly usable. Redaction must see raw
            # text. Snippets from search_vault are already clean; this re-run
            # covers callers that build hits by hand.
            context = "\n\n".join(
                f"[{h['note']}] {self._clean_for_speech(redact_secrets(h['snippet']))[:600]}"
                for h in hits
            )
            prompt = (
                f"Question: {query}\n\n"
                f"Excerpts from the user's Obsidian vault:\n{context}\n\n"
                "Answer the question using only these excerpts."
            )
            system = (
                "You are Viv, a knowledge companion reading the user's own notes aloud. "
                "Answer in at most two sentences of plain spoken English. "
                "Name the note you drew from. Use no markdown, lists, or symbols. "
                "If the excerpts do not answer the question, say so plainly."
            )

            result = engine.generate_completion(
                prompt=prompt,
                system_instruction=system,
                max_output_tokens=200,
                timeout=_SYNTHESIS_TIMEOUT_S,
            )
            if not result:
                return None
            return self._clean_for_speech(result)
        except Exception as e:
            logger.warning("vault answer synthesis failed: %s", e)
            return None


# ----------------------------------------------------------------------
# Intent detection
# ----------------------------------------------------------------------

_QUESTION_OPENERS = (
    "what", "when", "where", "who", "whose", "why", "how", "which",
    "did", "do", "does", "is", "are", "was", "were", "can", "could",
    "should", "would", "will", "have", "has", "had",
)

_LOOKUP_PHRASES = (
    "remind me",
    "look up",
    "look for",
    "search for",
    "search my",
    "find my",
    "find the",
    "find that",
    "what did i",
    "where did i",
    "when did i",
    "do i have",
    "tell me about",
    "pull up",
    "read me",
)


def is_vault_question(text: str) -> bool:
    """
    Decide whether spoken text is a question to answer from the vault or a
    thought to capture into the daily note.

    Capture is the safe default: a misrouted question is merely unhelpful, but
    a misrouted thought is lost from the note the user expected it in.
    """
    clean = text.strip()
    if not clean:
        return False

    lowered = clean.lower()

    if lowered.startswith(_LOOKUP_PHRASES) or any(p in lowered for p in _LOOKUP_PHRASES):
        return True

    # An explicit question mark is a strong signal on its own.
    if clean.endswith("?"):
        return True

    first = re.findall(r"\b\w+\b", lowered)
    if first and first[0] in _QUESTION_OPENERS:
        # Short openers are exclamations, not lookups: "what a mess",
        # "how annoying". A real spoken question carries more words.
        return len(first) >= 4

    return False
