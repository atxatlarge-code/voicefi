"""
Phonetic & Spoken-Code Self-Learning Engine for VoiceFi.
Continuously learns developer vocabulary, spoken syntax shorthands, and project-specific symbols.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


DEFAULT_BUILTIN_CORRECTIONS: Dict[str, str] = {
    r"\bpie\s*test\b": "pytest",
    r"\bpie\s*test\s+dash\s+v\b": "pytest -v",
    r"\bpie\s*test\s+dash\s+q\b": "pytest -q",
    r"\bwifi\b": "vifi",
    r"\bvoice\s*fi\b": "VoiceFi",
    r"\bvoice\s*fie\b": "VoiceFi",
    r"\bv\s*i\s*f\s*i\b": "vifi",
    r"\bcube\s*cuddle\b": "kubectl",
    r"\bcube\s*control\b": "kubectl",
    r"\bdock\s*er\s*compose\b": "docker compose",
    r"\bpie\s*project\b": "pyproject.toml",
    r"\bdot\s*t\s*s\s*x\b": ".tsx",
    r"\bdot\s*t\s*s\b": ".ts",
    r"\bdot\s*p\s*y\b": ".py",
    r"\bdot\s*pie\b": ".py",
    r"\bdot\s*py\b": ".py",
    r"\bdot\s*j\s*s\s*o\s*n\b": ".json",
    r"\bdot\s*y\s*a\s*m\s*l\b": ".yaml",
    r"\bdot\s*m\s*d\b": ".md",
    r"\bdot\s*e\s*n\s*v\b": ".env",
    r"\bgit\s*checkout\s*dash\s*b\b": "git checkout -b",
    r"\bgit\s*status\s*dash\s*s\b": "git status -s",
    r"\bcamel\s*case\b": "camelCase",
    r"\bsnake\s*case\b": "snake_case",
    r"\bkebab\s*case\b": "kebab-case",
}


def get_default_learning_dir() -> Path:
    """Return standard VoiceFi user configuration and learning directory."""
    path = Path.home() / ".voicefi"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_phonetic_memory_path() -> Path:
    """Return path to persistent phonetic memory file."""
    return get_default_learning_dir() / "phonetic_memory.json"


class PhoneticLearner:
    """
    Self-learning engine that resolves acoustic speech-to-text misrecognitions into precise code and CLI commands.
    """

    _instance: Optional["PhoneticLearner"] = None

    def __init__(self, memory_path: Optional[Path] = None):
        self.memory_path = memory_path or get_phonetic_memory_path()
        self.learned_corrections: Dict[str, Dict[str, Any]] = {}
        self.project_symbols: Dict[str, str] = {}
        self._load_memory()

    @classmethod
    def get_instance(cls) -> "PhoneticLearner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_memory(self):
        """Load persistent phonetic memory from JSON disk cache."""
        COMMON_WORDS = {
            "run",
            "get",
            "set",
            "is",
            "has",
            "do",
            "make",
            "find",
            "test",
            "load",
            "save",
            "stop",
            "read",
            "write",
            "open",
            "close",
        }
        if self.memory_path.is_file():
            try:
                with open(self.memory_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.learned_corrections = data.get("corrections", {})
                    raw_symbols = data.get("symbols", {})
                    self.project_symbols = {
                        k: v
                        for k, v in raw_symbols.items()
                        if isinstance(v, str)
                        and not v.startswith("_")
                        and v.lower() not in COMMON_WORDS
                    }
            except Exception:
                self.learned_corrections = {}
                self.project_symbols = {}
        else:
            self.learned_corrections = {}
            self.project_symbols = {}

    def _save_memory(self):
        """Atomically persist phonetic memory to disk."""
        try:
            tmp_path = self.memory_path.with_suffix(".tmp")
            data = {
                "version": 1,
                "corrections": self.learned_corrections,
                "symbols": self.project_symbols,
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.memory_path)
        except Exception:
            pass

    def record_correction(self, spoken: str, canonical: str, confidence: float = 1.0) -> None:
        """
        Record a developer correction (e.g. spoken: 'wifi tier', canonical: 'vifi tier').
        Recursively increments usage frequency and confidence score.
        """
        spoken_clean = spoken.strip().lower()
        canonical_clean = canonical.strip()
        if not spoken_clean or not canonical_clean or spoken_clean == canonical_clean.lower():
            return

        pattern = r"\b" + re.escape(spoken_clean) + r"\b"
        entry = self.learned_corrections.get(
            pattern,
            {
                "canonical": canonical_clean,
                "spoken": spoken_clean,
                "count": 0,
                "confidence": confidence,
            },
        )
        entry["canonical"] = canonical_clean
        entry["count"] = entry.get("count", 0) + 1
        entry["confidence"] = min(1.0, entry.get("confidence", 0.8) + 0.05)
        self.learned_corrections[pattern] = entry
        self._save_memory()

    def record_symbol(self, symbol: str) -> None:
        """
        Register a project identifier (e.g. 'UnifiedDynamicIslandHUD' or 'FeatureGate').
        Generates phonetic lookup tokens automatically.
        """
        sym_clean = symbol.strip()
        if not sym_clean or len(sym_clean) < 3 or sym_clean.startswith("_"):
            return

        # Skip common single English words from overriding dictionary
        COMMON_WORDS = {
            "run",
            "get",
            "set",
            "is",
            "has",
            "do",
            "make",
            "find",
            "test",
            "load",
            "save",
            "stop",
            "read",
            "write",
            "open",
            "close",
        }
        if sym_clean.lower() in COMMON_WORDS:
            return

        # Split CamelCase or snake_case into spoken words
        words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+", sym_clean)
        if words and len(words) > 1:
            spoken_form = " ".join(words).lower()
            pattern = r"\b" + re.escape(spoken_form) + r"\b"
            self.project_symbols[pattern] = sym_clean

    def get_all_symbols(self) -> List[str]:
        """Return all unique indexed project symbols."""
        return sorted(list(set(self.project_symbols.values())))

    def get_symbol_candidates(self, text: str, limit: int = 30) -> List[str]:
        """Return candidate project symbols based on token overlap or prefix matching."""
        if not text:
            return self.get_all_symbols()[:limit]

        words = set(re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower()))
        all_syms = self.get_all_symbols()
        scored: List[Tuple[int, str]] = []

        for sym in all_syms:
            sym_lower = sym.lower()
            score = 0
            for w in words:
                if len(w) >= 3:
                    if w in sym_lower:
                        score += 3
                    elif sym_lower.startswith(w[:3]):
                        score += 1
            if score > 0:
                scored.append((score, sym))

        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            return [s[1] for s in scored[:limit]]
        return all_syms[:limit]

    def normalize_stt(self, raw_text: str, enable_ai_fallback: bool = False) -> str:
        """
        Transform raw Whisper STT dictation into canonical code and syntax
        by recursively evaluating built-ins, learned corrections, and project symbols.
        Optionally attempts AI phonetic disambiguation for ambiguous spoken phrases.
        """
        if not raw_text or not raw_text.strip():
            return ""

        result = raw_text

        # 1. Built-in developer shorthands
        for pattern, replacement in DEFAULT_BUILTIN_CORRECTIONS.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # 2. Learned developer corrections
        for pattern, data in self.learned_corrections.items():
            canonical = data.get("canonical", "")
            if canonical:
                result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)

        # 3. Project-specific symbols
        for pattern, canonical in self.project_symbols.items():
            result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)

        # 4. Optional AI disambiguation on ambiguous terms if configured
        if enable_ai_fallback and self.project_symbols:
            try:
                from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine

                gem = GeminiIntelligenceEngine()
                if gem.is_available() and getattr(
                    getattr(gem.config, "gemini", None), "enable_phonetic_resolver", True
                ):
                    candidates = self.get_symbol_candidates(result, limit=25)
                    if candidates:
                        resolved = gem.resolve_phonetic_code(result, candidates, timeout=0.5)
                        if resolved:
                            result = resolved
            except Exception:
                pass

        return result

    def scan_workspace(self, workspace_path: Path) -> int:
        """
        Recursively scan the active repository to extract symbol names and index them.
        Returns the number of indexed project symbols.
        """
        if not workspace_path.is_dir():
            return 0

        found_count = 0
        file_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go"}

        for root, dirs, files in os.walk(workspace_path):
            # Skip hidden and vendor dirs
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "venv", ".venv", "dist", "build")
            ]
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in file_exts:
                    file_path = Path(root) / file
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            # Extract class and def names
                            classes = re.findall(r"\bclass\s+([A-Za-z0-9_]+)", content)
                            functions = re.findall(r"\bdef\s+([A-Za-z0-9_]+)", content)
                            ts_funcs = re.findall(r"\bfunction\s+([A-Za-z0-9_]+)", content)
                            ts_types = re.findall(
                                r"\b(?:interface|type)\s+([A-Za-z0-9_]+)", content
                            )

                            for sym in classes + functions + ts_funcs + ts_types:
                                if len(sym) >= 4:
                                    self.record_symbol(sym)
                                    found_count += 1
                    except Exception:
                        pass
                elif file in ("pyproject.toml", "package.json", "Cargo.toml"):
                    self.record_symbol(file)
                    found_count += 1

        self._save_memory()
        return found_count

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic metrics of learned vocabulary."""
        return {
            "total_learned_corrections": len(self.learned_corrections),
            "total_project_symbols": len(self.project_symbols),
            "top_corrections": [
                {
                    "spoken": v.get("spoken", k),
                    "canonical": v.get("canonical", ""),
                    "count": v.get("count", 0),
                }
                for k, v in sorted(
                    self.learned_corrections.items(),
                    key=lambda item: item[1].get("count", 0),
                    reverse=True,
                )[:10]
            ],
            "memory_file": str(self.memory_path),
        }

    def reset(self) -> None:
        """Reset learned memory."""
        self.learned_corrections = {}
        self.project_symbols = {}
        if self.memory_path.is_file():
            try:
                self.memory_path.unlink()
            except Exception:
                pass
