"""
Developer STT Biasing & Phonetic Normalizer.
Extracts project symbols, git branch, and dependencies to bias Speech-to-Text decoding,
and normalizes spoken developer jargon into clean syntax.
"""

import os
import re
import time
from pathlib import Path
from typing import List, Optional, Set, Dict, Callable


class ProjectContextExtractor:
    """Extracts project terminology to bias STT models towards relevant developer vocabulary."""

    def __init__(self, root_dir: Optional[Path] = None, max_symbols: int = 40):
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.max_symbols = max_symbols
        self._cached_prompt: Optional[str] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 30.0  # Cache for 30 seconds

    def extract_symbols(self) -> List[str]:
        """Extract key symbols, filenames, git branch, and framework terms from current workspace."""
        symbols: Set[str] = set()

        # 1. Common core dev & project keywords
        symbols.update(["VoiceFi", "Antigravity", "Python", "TypeScript", "macOS", "CLI", "API"])

        # 2. Git branch name if available
        try:
            git_head = self.root_dir / ".git" / "HEAD"
            if git_head.is_file():
                content = git_head.read_text(encoding="utf-8").strip()
                if content.startswith("ref: refs/heads/"):
                    branch = content.replace("ref: refs/heads/", "").strip()
                    symbols.add(branch)
                    for part in re.split(r"[/_-]", branch):
                        if len(part) > 2:
                            symbols.add(part)
        except Exception:
            pass

        # 3. Top-level files and src directory components
        try:
            for item in self.root_dir.iterdir():
                if item.name.startswith(".") or item.name in ("venv", "node_modules", "dist", "build", "__pycache__"):
                    continue
                name_clean = item.stem
                if len(name_clean) >= 3:
                    symbols.add(name_clean)

            # Look into src/ or lib/ if present
            src_dir = self.root_dir / "src"
            if src_dir.is_dir():
                for sub in src_dir.iterdir():
                    if not sub.name.startswith("."):
                        symbols.add(sub.stem)
        except Exception:
            pass

        # 4. Dependency manifests (pyproject.toml, package.json)
        try:
            pyproject = self.root_dir / "pyproject.toml"
            if pyproject.is_file():
                text = pyproject.read_text(encoding="utf-8")
                # Look for project name
                name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', text)
                if name_match:
                    symbols.add(name_match.group(1))

            pkg_json = self.root_dir / "package.json"
            if pkg_json.is_file():
                text = pkg_json.read_text(encoding="utf-8")
                name_match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
                if name_match:
                    symbols.add(name_match.group(1))
        except Exception:
            pass

        # Format and limit list
        clean_list = [s for s in sorted(symbols) if re.match(r"^[A-Za-z0-9_-]+$", s)]
        return clean_list[: self.max_symbols]

    def get_bias_prompt(self, extra_words: Optional[List[str]] = None) -> str:
        """Get biased prompt prefix for Whisper or Groq."""
        now = time.time()
        if self._cached_prompt and (now - self._cache_time) < self._cache_ttl and not extra_words:
            return self._cached_prompt

        symbols = self.extract_symbols()
        if extra_words:
            symbols.extend(extra_words)

        # Standard technical glossary additions
        dev_terms = ["pytest", "kubectl", "docker", "git", "PR", "FastAPI", "Next.js", "Whisper", "VAD", "STT", "TTS"]
        all_terms = list(dict.fromkeys(dev_terms + symbols))
        prompt = f"Technical context and developer vocabulary: {', '.join(all_terms)}."

        if not extra_words:
            self._cached_prompt = prompt
            self._cache_time = now

        return prompt


class PhoneticNormalizer:
    """Normalizes spoken developer slang, commands, and naming conventions."""

    # Static phonetic replacements
    REPLACEMENTS: Dict[str, str] = {
        r"\bpie\s*test\b": "pytest",
        r"\bpi\s*test\b": "pytest",
        r"\bcube\s*cuddle\b": "kubectl",
        r"\bcube\s*control\b": "kubectl",
        r"\bkube\s*ctl\b": "kubectl",
        r"\bkube\s*control\b": "kubectl",
        r"\bdock\s*er\b": "docker",
        r"\bfast\s*a\s*p\s*i\b": "FastAPI",
        r"\bfast\s*api\b": "FastAPI",
        r"\bnext\s*j\s*s\b": "Next.js",
        r"\bnext\s*js\b": "Next.js",
        r"\bnode\s*j\s*s\b": "Node.js",
        r"\bnode\s*js\b": "Node.js",
        r"\bget\s*hub\b": "GitHub",
        r"\bgit\s*hub\b": "GitHub",
        r"\bgit\s*check\s*out\b": "git checkout",
        r"\bgit\s*com\s*mit\b": "git commit",
        r"\bgit\s*pul\b": "git pull",
        r"\bgit\s*ref\s*log\b": "git reflog",
        r"\bn\s*p\s*m\b": "npm",
        r"\bp\s*r\b": "PR",
        r"\bp\s*w\s*a\b": "PWA",
        r"\bu\s*i\b": "UI",
        r"\bu\s*x\b": "UX",
        r"\bv\s*a\s*d\b": "VAD",
        r"\bs\s*t\s*t\b": "STT",
        r"\bt\s*t\s*s\b": "TTS",
        r"\bh\s*u\s*d\b": "HUD",
        r"\bdot\s*py\b": ".py",
        r"\bdot\s*ts\b": ".ts",
        r"\bdot\s*tsx\b": ".tsx",
        r"\bdot\s*js\b": ".js",
        r"\bdot\s*json\b": ".json",
        r"\bdot\s*md\b": ".md",
    }

    @classmethod
    def normalize(cls, text: str) -> str:
        """Transform raw transcribed text using phonetic developer rules, deduplication, and case converters."""
        if not text:
            return ""

        result = text.strip()

        # 1. Collapse consecutive word/phrase repetition loops (STT hallucination artifact)
        result = cls._collapse_repetitions(result)

        # 2. Case transformation directives (e.g. "camel case user id" -> "userId", "snake case get user info" -> "get_user_info")
        result = cls._apply_casing_directives(result)

        # 3. Apply phonetic term replacements
        for pattern, replacement in cls.REPLACEMENTS.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # 4. Apply recursive self-learned phonetic memory & project symbols
        try:
            from voicefi.learning.phonetic import PhoneticLearner
            result = PhoneticLearner.get_instance().normalize_stt(result)
        except Exception:
            pass

        return result

    @staticmethod
    def _collapse_repetitions(text: str) -> str:
        """Collapse consecutive repeated words or multi-word phrases caused by STT hallucination loops."""
        if not text:
            return ""

        # Collapse consecutive identical single words: "word word word" -> "word"
        text = re.sub(r'\b([A-Za-z0-9_-]+)(?:\s+\1\b)+', r'\1', text, flags=re.IGNORECASE)

        # Collapse consecutive multi-word phrases (2 to 5 words)
        words = text.split()
        if len(words) < 4:
            return text

        changed = True
        while changed:
            changed = False
            n = len(words)
            for phrase_len in range(min(5, n // 2), 1, -1):
                for i in range(n - 2 * phrase_len + 1):
                    p1 = [w.lower().strip(".,!?;:") for w in words[i : i + phrase_len]]
                    p2 = [w.lower().strip(".,!?;:") for w in words[i + phrase_len : i + 2 * phrase_len]]
                    if p1 == p2:
                        words = words[: i + phrase_len] + words[i + 2 * phrase_len :]
                        changed = True
                        break
                if changed:
                    break

        return " ".join(words)

    @staticmethod
    def _apply_casing_directives(text: str) -> str:
        """Convert spoken case directives (camel case, snake case, kebab case)."""
        stop_pattern = r"(?:\b(?:to|as|equal|equals|is|with|for|returns|return|in|and|of|from)\b|[.,!?;:]|$)"

        def _process_casing(raw_target: str, transform_fn: Callable[[List[str]], str]) -> str:
            # Check if there is a stop word or trailing clause
            match_stop = re.search(rf"(\s+{stop_pattern})", raw_target, flags=re.IGNORECASE)
            if match_stop:
                target_str = raw_target[:match_stop.start()].strip()
                remainder = raw_target[match_stop.start():]
            else:
                words = raw_target.strip().split()
                # Limit target identifier to first 4 words max
                if len(words) > 4:
                    target_str = " ".join(words[:4])
                    remainder = " " + " ".join(words[4:])
                else:
                    target_str = " ".join(words)
                    remainder = ""

            target_words = target_str.split()
            if not target_words:
                return raw_target
            return transform_fn(target_words) + remainder

        def _to_camel(match):
            return _process_casing(
                match.group(1),
                lambda words: words[0].lower() + "".join(w.capitalize() for w in words[1:])
            )

        def _to_snake(match):
            return _process_casing(
                match.group(1),
                lambda words: "_".join(w.lower() for w in words)
            )

        def _to_kebab(match):
            return _process_casing(
                match.group(1),
                lambda words: "-".join(w.lower() for w in words)
            )

        text = re.sub(r"\bcamel[_\s]*case\s+([a-zA-Z0-9\s.,!?;:]+?)(?=\b(?:camel|snake|kebab)[_\s]*case\b|$)", _to_camel, text, flags=re.IGNORECASE)
        text = re.sub(r"\bsnake[_\s]*case\s+([a-zA-Z0-9\s.,!?;:]+?)(?=\b(?:camel|snake|kebab)[_\s]*case\b|$)", _to_snake, text, flags=re.IGNORECASE)
        text = re.sub(r"\bkebab[_\s]*case\s+([a-zA-Z0-9\s.,!?;:]+?)(?=\b(?:camel|snake|kebab)[_\s]*case\b|$)", _to_kebab, text, flags=re.IGNORECASE)

        return text
