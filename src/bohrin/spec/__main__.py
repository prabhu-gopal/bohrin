"""Print the weakness list as Markdown: ``python -m bohrin.spec > docs/WEAKNESSES.md``."""

from __future__ import annotations

from bohrin.spec.weaknesses import render_markdown

print(render_markdown(), end="")
