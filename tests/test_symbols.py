"""
Unit tests for VoiceFi LocalSymbolIndex.
Verifies AST symbol indexing, SQLite caching, and instant lookup.
"""

import tempfile
from pathlib import Path
import pytest

from voicefi.local.symbols import LocalSymbolIndex, SymbolRecord


@pytest.fixture
def temp_repo(tmp_path):
    # Create sample python files
    mod_a = tmp_path / "engine.py"
    mod_a.write_text(
        '''
class Engine:
    """The main engine."""
    def start(self, timeout: int = 10):
        """Start the engine."""
        return True

    async def run_async(self, query: str):
        return query.upper()

def standalone_helper(x, y):
    return x + y
'''
    )

    pkg = tmp_path / "subpkg"
    pkg.mkdir()
    mod_b = pkg / "tools.py"
    mod_b.write_text(
        '''
class ToolRegistry:
    def register_tool(self, name, fn):
        pass
'''
    )
    return tmp_path


def test_symbol_indexing_and_lookup(temp_repo):
    db_file = temp_repo / "test_symbols.db"
    index = LocalSymbolIndex(db_path=db_file, root_dir=temp_repo)

    count = index.index_repo(temp_repo)
    assert count >= 4

    # 1. Exact function lookup
    funcs = index.find_symbol("standalone_helper")
    assert len(funcs) == 1
    assert funcs[0].name == "standalone_helper"
    assert funcs[0].kind == "function"
    assert funcs[0].signature == "(x, y)"

    # 2. Class and method lookup
    classes = index.find_symbol("Engine")
    assert len(classes) == 1
    assert classes[0].kind == "class"
    assert "main engine" in classes[0].docstring

    methods = index.find_symbol("start")
    assert len(methods) == 1
    assert methods[0].kind == "method"
    assert methods[0].parent_class == "Engine"
    assert "(self, timeout)" in methods[0].signature

    async_methods = index.find_symbol("run_async")
    assert len(async_methods) == 1
    assert async_methods[0].kind == "async_method"

    # 3. Fuzzy search
    res = index.search_symbols("register")
    assert len(res) >= 1
    assert res[0].name == "register_tool"

    # 4. Cache hit check
    count_second = index.index_repo(temp_repo)
    assert count_second == 0  # No files modified, 0 re-indexed


def test_ensure_fresh_auto_refresh(temp_repo):
    db_file = temp_repo / "test_symbols_fresh.db"
    index = LocalSymbolIndex(db_path=db_file)

    # Initial index
    index.index_repo(temp_repo)
    assert len(index.find_symbol("newly_added_helper", root_dir=temp_repo)) == 0

    # Append new function to engine.py
    import time
    time.sleep(0.05)  # Ensure mtime updates
    engine_file = temp_repo / "engine.py"
    with open(engine_file, "a") as f:
        f.write("\ndef newly_added_helper(token: str):\n    return token.strip()\n")

    # Force min_interval = 0 so ensure_fresh triggers
    index._last_check = 0.0

    # find_symbol should auto-refresh and discover newly_added_helper
    found = index.find_symbol("newly_added_helper", root_dir=temp_repo, auto_refresh=True)
    assert len(found) == 1
    assert found[0].name == "newly_added_helper"
    assert found[0].kind == "function"

