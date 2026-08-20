"""Unit tests for Antigravity transcript parsing and markdown speech cleaner."""

import json
from pathlib import Path
from talk2me.integrations.antigravity import clean_markdown_for_speech, extract_latest_agent_summary


def test_clean_markdown_strips_code_blocks():
    markdown = """
    I have created the files. Here is the code:
    ```python
    def hello():
        print("world")
    ```
    Would you like to run the test suite now?
    """
    cleaned = clean_markdown_for_speech(markdown, max_words=60)
    assert "def hello():" not in cleaned
    assert "Would you like to run the test suite now?" in cleaned


def test_clean_markdown_strips_links_and_headers():
    markdown = """
    # Project Update
    Please check [documentation](file:///Users/test/docs.md) and run `pytest`.
    """
    cleaned = clean_markdown_for_speech(markdown, max_words=60)
    assert "#" not in cleaned
    assert "file:///" not in cleaned
    assert "documentation" in cleaned
    assert "pytest" in cleaned


def test_extract_latest_agent_summary_from_transcript(tmp_path: Path):
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "Please implement feature X."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "I am working on feature X now."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Feature X has been implemented and tested successfully! What would you like to build next?"},
    ]

    with open(transcript_file, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")

    summary = extract_latest_agent_summary(transcript_file, max_words=50)
    assert "Feature X has been implemented" in summary
    assert "What would you like to build next?" in summary
