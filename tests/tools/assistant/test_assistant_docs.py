"""F48 step S10: ``docs/assistant.md`` and Help ▸ Guides ▸ AI assistant (01 PR-F48-31;
05 SEC-F48-23; 07 I-4): AC-F48-58."""

import re

from engine.core.paths import engine_root
from engine.tools.editor import guides

DOC = engine_root() / "docs" / "assistant.md"


def _text() -> str:
    return re.sub(r"\s+", " ", DOC.read_text(encoding="utf-8"))


def test_ac_f48_58_help_guides_lists_ai_assistant():
    assert ("AI assistant", "assistant.md") in guides.GUIDES
    assert DOC.is_file() and guides.guide_path("assistant.md") == DOC


def test_ac_f48_58_the_guide_covers_setup_privacy_mcp_and_local_models():
    text = _text()
    for heading in ("## Set up the pane", "## What is sent", "## Where the key is kept",
                    "## Use an AI app (MCP)", "## Be careful with games you didn't write"):
        assert heading in DOC.read_text(encoding="utf-8"), heading
    for point in ("File ▸ Studio settings…", "Help ▸ Connect an AI app…",
                  "http://localhost:11434/v1", "Pictures and sounds are never sent",
                  "Use the key from"):
        assert point in text, point


def test_ac_f48_58_the_five_sec_f48_23_points_and_the_key_variables():
    text = _text()
    points = (
        "Game files can carry instructions to the AI",                      # injection
        "the app's own tools can act on those instructions",                # MCP client tools
        "Don't auto-approve those tools, or `apply_edit`",
        "MCP checks run the game's code",                                   # --no-launch
        "start the server with `--no-launch`",
        "Programs you run can read the key's store",                        # key store
        "With a local server, nothing leaves your computer",                # local server
        "Preview, Check and Build don't pass `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` on",
    )
    for point in points:
        assert point in text, point
    assert "node" not in text.lower().split()
