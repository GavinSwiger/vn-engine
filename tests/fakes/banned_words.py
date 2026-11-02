"""Words no player-facing message may contain (PR-F02-31, AC-F02-38; used by F02's, F03's, and
F44's message tests): parser jargon, the cased ones only as whole upper-case words."""

import re

BANNED_CASED = re.compile(r"\b(INDENT|DEDENT|EOF|AST)\b")
BANNED_ANY = re.compile(r"\b(tokens?|parse|parsed|parser|parsing|nodes?|lexer)\b", re.I)
