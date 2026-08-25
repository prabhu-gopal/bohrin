"""The renderer contract — Stage ⑥ (docs/02 §6, §10).

One ``Report`` object, several renderers chosen by flag. A renderer is a pure sink: it
turns a finished ``Report`` into an output (terminal text, HTML, JSON) and never mutates
it. Adding an output format is one class over the frozen ``Report`` — the pipeline is
unchanged.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bohrin.report.model import Report


@runtime_checkable
class Renderer(Protocol):
    """Renders a finished :class:`Report` to some destination."""

    def render(self, report: Report) -> str:
        """Produce the rendered output (and, for file renderers, write it)."""
        ...
