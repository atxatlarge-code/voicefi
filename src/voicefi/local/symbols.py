"""
VoiceFi Local Symbol Indexer.
Extracts and indexes AST symbols (classes, methods, functions) into SQLite for
sub-millisecond lookups by local models without reading raw files into context.
"""

import os
import ast
import sqlite3
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Union

logger = logging.getLogger("voicefi.local.symbols")

DB_PATH = Path.home() / ".voicefi" / "symbols.db"


@dataclass
class SymbolRecord:
    name: str
    kind: str  # "function", "class", "method", "async_function"
    file_path: str
    start_line: int
    end_line: int
    parent_class: Optional[str] = None
    signature: str = ""
    docstring: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "parent_class": self.parent_class,
            "signature": self.signature,
            "docstring": self.docstring,
        }


class LocalSymbolIndex:
    """Fast SQLite-backed symbol index for Python codebases."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        root_dir: Optional[Union[str, Path]] = None,
    ):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.root_dir = Path(root_dir).resolve() if root_dir else None
        self._last_check: float = 0.0
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_meta (
                    path TEXT PRIMARY KEY,
                    mtime REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    kind TEXT,
                    file_path TEXT,
                    start_line INTEGER,
                    end_line INTEGER,
                    parent_class TEXT,
                    signature TEXT,
                    docstring TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sym_path ON symbols(file_path)")

    def index_repo(self, root_dir: Optional[Union[str, Path]] = None) -> int:
        """Scan and index all python files under root_dir incrementally."""
        target = root_dir or self.root_dir or "."
        root = Path(target).resolve()
        indexed_count = 0

        # Gather files
        py_files = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden and cache dirs
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in ("venv", ".venv", "node_modules", "dist", "build", "__pycache__")
            ]
            for f in filenames:
                if f.endswith(".py"):
                    py_files.append(Path(dirpath) / f)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for p in py_files:
                try:
                    stat = p.stat()
                    cursor.execute("SELECT mtime FROM file_meta WHERE path = ?", (str(p),))
                    row = cursor.fetchone()
                    if row and row["mtime"] >= stat.st_mtime:
                        continue  # Cache hit, file hasn't changed

                    # Re-index file
                    symbols = self._parse_file(p)
                    cursor.execute("DELETE FROM symbols WHERE file_path = ?", (str(p),))
                    for s in symbols:
                        cursor.execute(
                            """
                            INSERT INTO symbols (name, kind, file_path, start_line, end_line, parent_class, signature, docstring)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                s.name,
                                s.kind,
                                s.file_path,
                                s.start_line,
                                s.end_line,
                                s.parent_class,
                                s.signature,
                                s.docstring,
                            ),
                        )
                    cursor.execute(
                        "INSERT OR REPLACE INTO file_meta (path, mtime) VALUES (?, ?)",
                        (str(p), stat.st_mtime),
                    )
                    indexed_count += len(symbols)
                except Exception as e:
                    logger.debug(f"Error indexing {p}: {e}")

            conn.commit()

        return indexed_count

    def _parse_file(self, path: Path) -> List[SymbolRecord]:
        symbols: List[SymbolRecord] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
            tree = ast.parse(source, filename=str(path))
        except Exception:
            return []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                symbols.append(
                    SymbolRecord(
                        name=node.name,
                        kind="class",
                        file_path=str(path),
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        docstring=doc[:150],
                    )
                )
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_doc = ast.get_docstring(item) or ""
                        kind = "async_method" if isinstance(item, ast.AsyncFunctionDef) else "method"
                        symbols.append(
                            SymbolRecord(
                                name=item.name,
                                kind=kind,
                                file_path=str(path),
                                start_line=item.lineno,
                                end_line=getattr(item, "end_lineno", item.lineno),
                                parent_class=node.name,
                                signature=self._format_args(item.args),
                                docstring=m_doc[:150],
                            )
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                f_doc = ast.get_docstring(node) or ""
                kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                symbols.append(
                    SymbolRecord(
                        name=node.name,
                        kind=kind,
                        file_path=str(path),
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        signature=self._format_args(node.args),
                        docstring=f_doc[:150],
                    )
                )

        return symbols

    def _format_args(self, args_node: ast.arguments) -> str:
        args_list = []
        for a in args_node.args:
            args_list.append(a.arg)
        if args_node.vararg:
            args_list.append(f"*{args_node.vararg.arg}")
        if args_node.kwarg:
            args_list.append(f"**{args_node.kwarg.arg}")
        return "(" + ", ".join(args_list) + ")"

    def ensure_fresh(
        self,
        root_dir: Optional[Union[str, Path]] = None,
        min_interval: float = 5.0,
    ) -> int:
        """Incrementally re-index files if min_interval seconds have elapsed since last check."""
        now = time.time()
        if now - self._last_check < min_interval:
            return 0
        self._last_check = now
        target_dir = root_dir or self.root_dir or Path.cwd()
        return self.index_repo(target_dir)

    def find_symbol(
        self,
        name: str,
        root_dir: Optional[Union[str, Path]] = None,
        auto_refresh: bool = True,
    ) -> List[SymbolRecord]:
        """Lookup exact symbol name across the codebase."""
        if auto_refresh:
            try:
                self.ensure_fresh(root_dir or self.root_dir)
            except Exception:
                pass

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM symbols WHERE name = ? ORDER BY kind DESC LIMIT 10",
                (name,),
            )
            rows = cursor.fetchall()
            return [
                SymbolRecord(
                    name=r["name"],
                    kind=r["kind"],
                    file_path=r["file_path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    parent_class=r["parent_class"],
                    signature=r["signature"] or "",
                    docstring=r["docstring"] or "",
                )
                for r in rows
            ]

    def search_symbols(
        self,
        query: str,
        limit: int = 15,
        root_dir: Optional[Union[str, Path]] = None,
        auto_refresh: bool = True,
    ) -> List[SymbolRecord]:
        """Fuzzy search symbol names matching query."""
        if auto_refresh:
            try:
                self.ensure_fresh(root_dir or self.root_dir)
            except Exception:
                pass

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM symbols WHERE name LIKE ? ORDER BY kind DESC LIMIT ?",
                (f"%{query}%", limit),
            )
            rows = cursor.fetchall()
            return [
                SymbolRecord(
                    name=r["name"],
                    kind=r["kind"],
                    file_path=r["file_path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    parent_class=r["parent_class"],
                    signature=r["signature"] or "",
                    docstring=r["docstring"] or "",
                )
                for r in rows
            ]
